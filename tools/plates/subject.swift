// Subject cut-out + background plate for 2.5D picture tiles.
// usage: subject <in> <outdir> <name> [--pick all|list|1,3] [--dilate px] [--roi x0,y0,x1,y1] [--fill-black]
//   --roi         look for the subject only inside this part of the picture (fractions), layers stay full size
//   --fill-black  also treat the black surround (connected to the corners) as background to fill in
// writes <name>-fg.png (subject, transparent), <name>-bg.png (subject removed and filled in), <name>-mask.png
import Foundation
import Vision
import CoreImage
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

func die(_ m: String) -> Never { FileHandle.standardError.write((m + "\n").data(using: .utf8)!); exit(1) }
let a = CommandLine.arguments
guard a.count >= 4 else { die("usage: subject <in> <outdir> <name> [--pick all|list|1,2] [--dilate px] [--roi x0,y0,x1,y1] [--fill-black]") }
let inURL = URL(fileURLWithPath: a[1]), outDir = URL(fileURLWithPath: a[2]), name = a[3]
var pick = "all", dilatePx = 10, roi: [Double] = [0, 0, 1, 1], fillBlack = false, blackMax = 30, fade = 0
var ai = 4
while ai < a.count {
	switch a[ai] {
	case "--pick": pick = a[ai + 1]; ai += 2
	case "--dilate": dilatePx = Int(a[ai + 1]) ?? 10; ai += 2
	case "--roi": roi = a[ai + 1].split(separator: ",").compactMap { Double($0) }; ai += 2
	case "--fill-black": fillBlack = true; ai += 1
	case "--black-max": blackMax = Int(a[ai + 1]) ?? 30; ai += 2
	case "--fade": fade = Int(a[ai + 1]) ?? 0; ai += 2
	default: die("unknown option \(a[ai])")
	}
}
guard roi.count == 4 else { die("--roi needs x0,y0,x1,y1") }

guard let src = CGImageSourceCreateWithURL(inURL as CFURL, nil), let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else { die("cannot read \(a[1])") }
let W = cg.width, H = cg.height
let rx = Int(roi[0] * Double(W)), ry = Int(roi[1] * Double(H))
let rw = min(W - rx, Int((roi[2] - roi[0]) * Double(W))), rh = min(H - ry, Int((roi[3] - roi[1]) * Double(H)))
guard let look = cg.cropping(to: CGRect(x: rx, y: ry, width: rw, height: rh)) else { die("bad --roi") }
let cs = CGColorSpace(name: CGColorSpace.sRGB)!
var rgba = [UInt8](repeating: 0, count: W * H * 4)
rgba.withUnsafeMutableBytes { p in
	let ctx = CGContext(data: p.baseAddress, width: W, height: H, bitsPerComponent: 8, bytesPerRow: W * 4, space: cs, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
	ctx.draw(cg, in: CGRect(x: 0, y: 0, width: W, height: H))
}

let handler = VNImageRequestHandler(cgImage: look, options: [:])
let req = VNGenerateForegroundInstanceMaskRequest()
do { try handler.perform([req]) } catch { die("vision failed: \(error)") }
guard let obs = req.results?.first else { die("no subject found") }
var inst = obs.allInstances
// area of every instance, from the low-resolution label map
do {
	let lab = obs.instanceMask
	CVPixelBufferLockBaseAddress(lab, .readOnly)
	let lw = CVPixelBufferGetWidth(lab), lh = CVPixelBufferGetHeight(lab), bpr = CVPixelBufferGetBytesPerRow(lab)
	let base = CVPixelBufferGetBaseAddress(lab)!.assumingMemoryBound(to: UInt8.self)
	var count = [Int: Int](), box = [Int: (Int, Int, Int, Int)]()
	for y in 0..<lh { for x in 0..<lw { let v = Int(base[y * bpr + x]); if v == 0 { continue }
		count[v, default: 0] += 1
		let b = box[v] ?? (x, y, x, y); box[v] = (min(b.0, x), min(b.1, y), max(b.2, x), max(b.3, y)) } }
	CVPixelBufferUnlockBaseAddress(lab, .readOnly)
	for k in count.keys.sorted() { let b = box[k]!
		print(String(format: "instance %d: %.1f%% of the frame, box x %.2f-%.2f y %.2f-%.2f", k, 100 * Double(count[k]!) / Double(lw * lh), Double(b.0) / Double(lw), Double(b.2) / Double(lw), Double(b.1) / Double(lh), Double(b.3) / Double(lh))) }
}
if pick == "list" { exit(0) }
if pick != "all" { inst = IndexSet(pick.split(separator: ",").compactMap { Int($0) }) }

let maskPB: CVPixelBuffer
do { maskPB = try obs.generateScaledMaskForImage(forInstances: inst, from: handler) } catch { die("mask failed: \(error)") }
CVPixelBufferLockBaseAddress(maskPB, .readOnly)
let mw = CVPixelBufferGetWidth(maskPB), mh = CVPixelBufferGetHeight(maskPB), mbpr = CVPixelBufferGetBytesPerRow(maskPB)
guard mw == rw, mh == rh else { die("mask size \(mw)x\(mh) differs from the searched area \(rw)x\(rh)") }
var mask = [Float](repeating: 0, count: W * H)
let mbase = CVPixelBufferGetBaseAddress(maskPB)!
for y in 0..<rh { let row = (mbase + y * mbpr).assumingMemoryBound(to: Float32.self); for x in 0..<rw { mask[(y + ry) * W + x + rx] = max(0, min(1, row[x])) } }
CVPixelBufferUnlockBaseAddress(maskPB, .readOnly)

func writePNG(_ bytes: [UInt8], _ w: Int, _ h: Int, _ comps: Int, _ url: URL) {
	let data = Data(bytes) as CFData
	let info: CGBitmapInfo = comps == 4 ? CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue) : CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue)
	let space = comps == 1 ? CGColorSpaceCreateDeviceGray() : cs
	let img = CGImage(width: w, height: h, bitsPerComponent: 8, bitsPerPixel: 8 * comps, bytesPerRow: w * comps, space: space, bitmapInfo: info, provider: CGDataProvider(data: data)!, decode: nil, shouldInterpolate: true, intent: .defaultIntent)!
	let dst = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
	CGImageDestinationAddImage(dst, img, nil); CGImageDestinationFinalize(dst)
}

// subject: source colour, alpha from the mask (premultiplied for CoreGraphics)
var fg = [UInt8](repeating: 0, count: W * H * 4)
for i in 0..<(W * H) { let m = mask[i]
	fg[i * 4] = UInt8(Float(rgba[i * 4]) * m); fg[i * 4 + 1] = UInt8(Float(rgba[i * 4 + 1]) * m); fg[i * 4 + 2] = UInt8(Float(rgba[i * 4 + 2]) * m); fg[i * 4 + 3] = UInt8(m * 255) }
writePNG(fg, W, H, 4, outDir.appendingPathComponent("\(name)-fg.png"))
writePNG(mask.map { UInt8($0 * 255) }, W, H, 1, outDir.appendingPathComponent("\(name)-mask.png"))

// background: drop the subject (grown by a few pixels so no fringe is left) and fill the hole by push-pull
var surround = [Bool]()
var hole = [Bool](repeating: false, count: W * H)
for i in 0..<(W * H) { hole[i] = mask[i] > 0.04 }
if dilatePx > 0 {   // separable square dilation
	var tmp = hole
	for y in 0..<H { var run = -1_000_000; for x in 0..<W { if hole[y * W + x] { run = x }; if x - run <= dilatePx { tmp[y * W + x] = true } }
		run = 1_000_000; for x in stride(from: W - 1, through: 0, by: -1) { if hole[y * W + x] { run = x }; if run - x <= dilatePx { tmp[y * W + x] = true } } }
	var out = tmp
	for x in 0..<W { var run = -1_000_000; for y in 0..<H { if tmp[y * W + x] { run = y }; if y - run <= dilatePx { out[y * W + x] = true } }
		run = 1_000_000; for y in stride(from: H - 1, through: 0, by: -1) { if tmp[y * W + x] { run = y }; if run - y <= dilatePx { out[y * W + x] = true } } }
	hole = out
}
if fillBlack {   // the black surround of a round (fisheye) picture: flood from the corners through near-black pixels
	var seen = [Bool](repeating: false, count: W * H), stack = [0, W - 1, (H - 1) * W, H * W - 1]
	func dark(_ i: Int) -> Bool { Int(max(rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2])) < blackMax }
	while let i = stack.popLast() {
		if seen[i] || !dark(i) { continue }
		seen[i] = true
		let x = i % W, y = i / W
		if x > 0 { stack.append(i - 1) }; if x < W - 1 { stack.append(i + 1) }; if y > 0 { stack.append(i - W) }; if y < H - 1 { stack.append(i + W) }
	}
	// grow by a few pixels so the dark rim goes too
	let g = 8
	var grown = seen
	for y in 0..<H { for x in 0..<W where seen[y * W + x] { for dy in stride(from: -g, through: g, by: g) { for dx in stride(from: -g, through: g, by: g) {
		let xx = x + dx, yy = y + dy; if xx >= 0 && xx < W && yy >= 0 && yy < H { grown[yy * W + xx] = true } } } } }
	var n = 0
	for i in 0..<(W * H) where grown[i] { hole[i] = true; n += 1 }
	surround = grown
	print(String(format: "black surround: %.1f%% of the picture filled in", 100 * Double(n) / Double(W * H)))
}
struct Level { var w: Int; var h: Int; var c: [Float]; var wt: [Float] }   // c = weighted colour (3 per pixel), wt = weight
var lv = [Level]()
var l0 = Level(w: W, h: H, c: [Float](repeating: 0, count: W * H * 3), wt: [Float](repeating: 0, count: W * H))
for i in 0..<(W * H) where !hole[i] { l0.wt[i] = 1; l0.c[i * 3] = Float(rgba[i * 4]); l0.c[i * 3 + 1] = Float(rgba[i * 4 + 1]); l0.c[i * 3 + 2] = Float(rgba[i * 4 + 2]) }
lv.append(l0)
while lv.last!.w > 1 || lv.last!.h > 1 {
	let p = lv.last!, w = max(1, (p.w + 1) / 2), h = max(1, (p.h + 1) / 2)
	var n = Level(w: w, h: h, c: [Float](repeating: 0, count: w * h * 3), wt: [Float](repeating: 0, count: w * h))
	for y in 0..<h { for x in 0..<w { var sw: Float = 0, r: Float = 0, g: Float = 0, b: Float = 0
		for dy in 0..<2 { for dx in 0..<2 { let sx = x * 2 + dx, sy = y * 2 + dy; if sx >= p.w || sy >= p.h { continue }
			let i = sy * p.w + sx; sw += p.wt[i]; r += p.c[i * 3]; g += p.c[i * 3 + 1]; b += p.c[i * 3 + 2] } }
		let i = y * w + x
		if sw > 0 { let k = min(sw, 1) / sw; n.wt[i] = min(sw, 1); n.c[i * 3] = r * k; n.c[i * 3 + 1] = g * k; n.c[i * 3 + 2] = b * k } } }
	lv.append(n)
}
for li in stride(from: lv.count - 2, through: 0, by: -1) {
	let coarse = lv[li + 1]; var fine = lv[li]
	for y in 0..<fine.h { for x in 0..<fine.w { let i = y * fine.w + x; let wgt = fine.wt[i]; if wgt >= 1 { continue }
		// bilinear sample of the coarser level
		let fx = (Float(x) + 0.5) / 2 - 0.5, fy = (Float(y) + 0.5) / 2 - 0.5
		let x0 = max(0, min(coarse.w - 1, Int(floor(fx)))), y0 = max(0, min(coarse.h - 1, Int(floor(fy))))
		let x1 = min(coarse.w - 1, x0 + 1), y1 = min(coarse.h - 1, y0 + 1)
		let tx = max(0, min(1, fx - Float(x0))), ty = max(0, min(1, fy - Float(y0)))
		var col: [Float] = [0, 0, 0]
		for ch in 0..<3 { let c00 = coarse.c[(y0 * coarse.w + x0) * 3 + ch], c10 = coarse.c[(y0 * coarse.w + x1) * 3 + ch], c01 = coarse.c[(y1 * coarse.w + x0) * 3 + ch], c11 = coarse.c[(y1 * coarse.w + x1) * 3 + ch]
			col[ch] = (c00 * (1 - tx) + c10 * tx) * (1 - ty) + (c01 * (1 - tx) + c11 * tx) * ty }
		for ch in 0..<3 { fine.c[i * 3 + ch] = fine.c[i * 3 + ch] + (1 - wgt) * col[ch] }
		fine.wt[i] = 1 } }
	lv[li] = fine
}
var bg = [UInt8](repeating: 255, count: W * H * 3)
for i in 0..<(W * H * 3) { bg[i] = UInt8(max(0, min(255, lv[0].c[i]))) }
if fade > 0 && !surround.isEmpty {   // the filled-in surround darkens with distance from the picture, like a lens edge
	var d = [Float](repeating: 0, count: W * H)
	for i in 0..<(W * H) where surround[i] { d[i] = 1e9 }
	for y in 0..<H { for x in 0..<W { let i = y * W + x; if d[i] == 0 { continue }
		var m = d[i]
		if x > 0 { m = min(m, d[i - 1] + 1) }; if y > 0 { m = min(m, d[i - W] + 1) }
		if x > 0 && y > 0 { m = min(m, d[i - W - 1] + 1.414) }; if x < W - 1 && y > 0 { m = min(m, d[i - W + 1] + 1.414) }
		d[i] = m } }
	for y in stride(from: H - 1, through: 0, by: -1) { for x in stride(from: W - 1, through: 0, by: -1) { let i = y * W + x; if d[i] == 0 { continue }
		var m = d[i]
		if x < W - 1 { m = min(m, d[i + 1] + 1) }; if y < H - 1 { m = min(m, d[i + W] + 1) }
		if x < W - 1 && y < H - 1 { m = min(m, d[i + W + 1] + 1.414) }; if x > 0 && y < H - 1 { m = min(m, d[i + W - 1] + 1.414) }
		d[i] = m } }
	for i in 0..<(W * H) where d[i] > 0 { let t = min(1, d[i] / Float(fade)); let k = 1 - 0.86 * (t * t * (3 - 2 * t))
		bg[i * 3] = UInt8(Float(bg[i * 3]) * k); bg[i * 3 + 1] = UInt8(Float(bg[i * 3 + 1]) * k); bg[i * 3 + 2] = UInt8(Float(bg[i * 3 + 2]) * k) }
}
writePNG(bg, W, H, 3, outDir.appendingPathComponent("\(name)-bg.png"))
print("wrote \(name)-fg.png \(name)-bg.png \(name)-mask.png (\(W)x\(H))")
