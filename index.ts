import { CanvasRenderingContext2D, createCanvas, Image, loadImage, registerFont } from "canvas";
import puppeteer from "puppeteer";
import fs from "fs/promises";

declare global {
	namespace NodeJS {
		interface ProcessEnv {
			NITTER_PAGE: string;
			BOLD_FONT_LOCATION: string;
			NORMAL_FONT_LOCATION: string;
			DEVICE: string;
			ALREADY_PRINTED_FILE: string;
			USER_AGENT: string;
			CHROMIUM_PATH: string;
			FONT_NAME: string;
			MAX_WIDTH_PX: string;
			REFRESH_MS: string;
		}
	}
}

const WIDTH = +process.env.MAX_WIDTH_PX;
const REFRESH_MS = +process.env.REFRESH_MS;

const printed = new Set();

type Tweet = {
	content: string;
	date: string;
	image?: string;
	username: string;
	avatar: string;
	id: string;
};
type Bitmap = {
	data: Buffer<ArrayBuffer>;
	bytesPerRow: number;
	heightPixels: number;
}

const BAYER8 = [
	[0,48,12,60,3,51,15,63],
	[32,16,44,28,35,19,47,31],
	[8,56,4,52,11,59,7,55],
	[40,24,36,20,43,27,39,23],
	[2,50,14,62,1,49,13,61],
	[34,18,46,30,33,17,45,29],
	[10,58,6,54,9,57,5,53],
	[42,26,38,22,41,25,37,21],
];

async function init() {
	for (const id of (await fs.readFile(process.env.ALREADY_PRINTED_FILE)).toString().split("\n")) {
		printed.add(id);
	}

	registerFont(process.env.NORMAL_FONT_LOCATION, { family: process.env.FONT_NAME, weight: "normal" });
	registerFont(process.env.BOLD_FONT_LOCATION, { family: process.env.FONT_NAME, weight: "bold" });

	await updateAndPrintTweets();
	setInterval(updateAndPrintTweets, REFRESH_MS);
}
init();

const formatDate = (d: Date) => new Intl.DateTimeFormat("en-US",{month:"numeric",day:"numeric",year:"numeric",hour:"numeric",minute:"2-digit",hour12:true}).format(d).replace(",", " -");

async function updateAndPrintTweets() {
	const browser = await puppeteer.launch({
		headless: true,
		executablePath: process.env.CHROMIUM_PATH,
		args: ["--no-sandbox"]
	});
	const page = await browser.newPage();

	await page.setUserAgent(process.env.USER_AGENT);
	await page.setRequestInterception(true);

	// Don't bog down Nitter instance by requesting images/scripts/etc; only allow html/document
	page.on("request", (req) => {
		if (req.resourceType() !== "document") {
			req.abort();
			return;
		}
		req.continue();
	});

	await page.goto(process.env.NITTER_PAGE, { waitUntil: "networkidle2" });

	// Extract tweets
	const tweets: Tweet[] = (await page.evaluate(() => (
		[...document.querySelectorAll("div.timeline-item:not(:has(.pinned)):not(:has(.retweet-header))")].map(tweet => ({
			content: tweet.querySelector(".tweet-content")?.textContent,
			date: (tweet.querySelector(".tweet-date > a") as HTMLElement)?.title.replace(/·/, ""),
			image: (tweet.querySelector(".still-image") as HTMLLinkElement)?.href,
			username: tweet.querySelector(".username")?.textContent,
			avatar: (tweet.querySelector(".avatar.round") as HTMLImageElement)?.src,
			id: (tweet.querySelector(".tweet-link") as HTMLLinkElement)?.href?.match?.(/(?<=status\/)\d+/)?.[0]
		}))
	))).map(x => ({...x, date: formatDate(new Date(x.date))}));

	const unprinted = tweets.filter(x => !printed.has(x.id));

	for (const tweet of unprinted) {
		console.log("Printing out this tweet: ", tweet);
		await sendToPrinter(await renderTweet(tweet));
		printed.add(tweet.id);
	}
	await fs.writeFile(process.env.ALREADY_PRINTED_FILE, [...printed].join("\n"));
	await browser.close();
}

async function renderTweet(tweet: Tweet) {
	const pimg = await loadImage(tweet.avatar);
	const aspect = pimg.width / pimg.height;
	const targetH = 40;
	const targetW = Math.max(1, Math.round(aspect * targetH));

	let imgObj: Image | null = null;
	let imgRenderW = 0;
	let imgRenderH = 0;
	if (tweet.image) {
		imgObj = await loadImage(tweet.image);
		imgRenderW = WIDTH;
		imgRenderH = Math.max(1, Math.round(imgObj.height * (imgRenderW / imgObj.width)));
	}

	// Create a dummy canvas to measure text
	const dummyCanvas = createCanvas(1, 1);
	const dctx = dummyCanvas.getContext("2d");

	const fontUser = `bold 24px ${process.env.FONT_NAME}, sans-serif`;
	const fontText = `22px ${process.env.FONT_NAME}, sans-serif`;
	const fontDate = `18px ${process.env.FONT_NAME}, sans-serif`;

	dctx.font = fontText;
	const lines = wrapTextPixels(tweet.content, dctx, WIDTH);

	// Profile + username line height
	dctx.font = fontUser;
	const usernameText = tweet.username;
	const usernameHeight = measureTextHeight(dctx, usernameText);
	const profileLineHeight = Math.max(targetH, usernameHeight);

	// Tweet text block height
	dctx.font = fontText;
	let tweetTextHeight = 0;
	const lineHeights: number[] = [];
	for (const line of lines) {
		const h = measureTextHeight(dctx, line);
		lineHeights.push(h);
		tweetTextHeight += (h + 4);
	}

	// Date height
	dctx.font = fontDate;
	const dateHeight = measureTextHeight(dctx, tweet.date);

	// Total canvas height, include image height if present
	const paddingTop = 8;
	const dateTopPadding = 2;
	const paddingBottom = 40;
	const spacing = 10;
	const imageBlockHeight = imgObj ? (imgRenderH + spacing) : 0;
	const totalHeight = paddingTop + profileLineHeight + spacing + tweetTextHeight + imageBlockHeight + dateTopPadding + dateHeight + paddingBottom;

	const canvas = createCanvas(WIDTH, totalHeight);
	const ctx = canvas.getContext("2d");

	ctx.fillStyle = "#ffffff";
	ctx.fillRect(0, 0, WIDTH, totalHeight);

	// Draw profile picture
	const profileCanvas = createCanvas(targetW, targetH);
	const pctx = profileCanvas.getContext("2d");

	pctx.drawImage(pimg, 0, 0, targetW, targetH);
	ctx.drawImage(profileCanvas, 0, paddingTop);

	ctx.fillStyle = "#000000";
	ctx.font = fontUser;
	ctx.textBaseline = "top";
	ctx.fillText(usernameText, targetW + 6, paddingTop);

	// Draw tweet text content
	let yOffset = paddingTop + profileLineHeight + spacing;
	ctx.font = fontText;
	ctx.textBaseline = "top";
	for (let i = 0; i < lines.length; i++) {
		const line = lines[i];
		ctx.fillText(line, 0, yOffset);
		yOffset += lineHeights[i] + 4;
	}

	// Draw image
	if (imgObj) {
		ctx.drawImage(imgObj, 0, yOffset, imgRenderW, imgRenderH);
		yOffset += imgRenderH + spacing;
	}

	// Draw date
	yOffset += dateTopPadding;
	ctx.font = fontDate;
	ctx.fillText(tweet.date, 0, yOffset);

	const imageData = ctx.getImageData(0, 0, WIDTH, totalHeight).data;

	return buildBitmapFromImageData(imageData, WIDTH, totalHeight);
}


function wrapTextPixels(text: string, ctx: CanvasRenderingContext2D, maxWidth: number) {
	const words = text.split(/\s+/);
	const lines: string[] = [];
	let currentLine = "";
	for (const word of words) {
		const testLine = currentLine ? (currentLine + " " + word) : word;
		const metrics = ctx.measureText(testLine);
		const lineWidth = metrics.width;
		if (lineWidth <= maxWidth) {
			currentLine = testLine;
		} else {
			if (currentLine) lines.push(currentLine);
			currentLine = word;
		}
	}
	if (currentLine) lines.push(currentLine);
	return lines;
}

function measureTextHeight(ctx: CanvasRenderingContext2D, text: string) {
	const m = ctx.measureText(text);
	if (typeof m.actualBoundingBoxAscent === "number" && typeof m.actualBoundingBoxDescent === "number") {
		return Math.ceil(m.actualBoundingBoxAscent + m.actualBoundingBoxDescent);
	}
	// fallback: approximate using font size from ctx.font "NNpx ..."
	const match = ctx.font.match(/(\d+)\s?px/);
	if (match) return parseInt(match[1], 10);
	return 16;
}

function buildBitmapFromImageData(imageData: Uint8ClampedArray, width: number, height: number): Bitmap {
	const pad = (8 - (width % 8)) % 8;
	const widthPadded = width + pad;
	const bytesPerRow = widthPadded / 8;

	const data = Buffer.alloc(bytesPerRow * height);

	const ditherPixel = (gray: number, x: number, y: number) => gray < Math.floor(BAYER8[y % 8][x % 8] * (255.0 / 64.0)) ? 1 : 0;

	for (let y = 0; y < height; y++) {
		const rowBits: number[] = [];
		for (let x = 0; x < widthPadded; x++) {
			let b = 0;
			if (x < width) {
				const idx = (y * width + x) * 4;
				const r = imageData[idx];
				const g = imageData[idx + 1];
				const bcol = imageData[idx + 2];
				const gray = Math.round(0.299 * r + 0.587 * g + 0.114 * bcol);
				b = ditherPixel(gray, x, y);
			} else {
				b = 0;
			}
			rowBits.push(b);
		}

		for (let byteI = 0; byteI < bytesPerRow; byteI++) {
			let val = 0;
			for (let bit = 0; bit < 8; bit++) {
				val <<= 1;
				val |= rowBits[byteI * 8 + bit];
			}
			data[y * bytesPerRow + byteI] = val & 0xFF;
		}
	}

	return { data, bytesPerRow, heightPixels: height };
}

async function sendToPrinter(bitmap: Bitmap) {
	const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

	const INIT = Buffer.from([0x1b, 0x40]);
	const m = 0;
	const xL = bitmap.bytesPerRow & 0xFF;
	const xH = (bitmap.bytesPerRow >> 8) & 0xFF;
	const yL = bitmap.heightPixels & 0xFF;
	const yH = (bitmap.heightPixels >> 8) & 0xFF;

	const header = Buffer.from([0x1d, 0x76, 0x30, m, xL, xH, yL, yH]);

	await fs.writeFile(process.env.DEVICE, Buffer.from("\n"), { flag: "a" });
	await sleep(20);

	await fs.writeFile(process.env.DEVICE, Buffer.concat([INIT, header]), { flag: "a" });
	await sleep(20);

	await fs.writeFile(process.env.DEVICE, bitmap.data, { flag: "a" });
}