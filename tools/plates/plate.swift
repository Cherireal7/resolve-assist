// Compose 2.5D picture plates from a filled background and a subject cut-out.
// usage: plate <spec.json>
// spec: {"out": dir, "plates": [{name, bg, fg, w, h, bgCrop: [x0, y0, width] (fractions of the background; height follows the canvas shape),
//         blur, fgScale, fgRef: [fx, fy] (point inside the subject picture), fgAt: [cx, cy] (where that point lands on the canvas), sharpen}],
//        "stickers": [{name, fg, max}]}
// writes <name>.jpg (background), <name>-fg.png (subject on a transparent canvas of the same size), <name>-preview.jpg
import Foundation
import CoreImage
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

func die(_ m: String) -> Never { FileHandle.standardError.write((m + "\n").data(using: .utf8)!); exit(1) }
guard CommandLine.arguments.count == 2, let raw = FileManager.default.contents(atPath: CommandLine.arguments[1]),
	let spec = try? JSONSerialization.jsonObject(with: raw) as? [String: Any] else { die("usage: plate <spec.json>") }
let outDir = URL(fileURLWithPath: spec["out"] as! String)
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
let cs = CGColorSpace(name: CGColorSpace.sRGB)!
let cictx = CIContext(options: [.workingColorSpace: cs])
func load(_ p: String) -> CGImage {
	guard let s = CGImageSourceCreateWithURL(URL(fileURLWithPath: p) as CFURL, nil), let i = CGImageSourceCreateImageAtIndex(s, 0, nil) else { die("cannot read \(p)") }
	return i
}
func save(_ img: CGImage, _ url: URL, jpeg: Bool) {
	let type = (jpeg ? UTType.jpeg : UTType.png).identifier as CFString
	let d = CGImageDestinationCreateWithURL(url as CFURL, type, 1, nil)!
	CGImageDestinationAddImage(d, img, jpeg ? [kCGImageDestinationLossyCompressionQuality: 0.92] as CFDictionary : nil)
	CGImageDestinationFinalize(d)
}
func canvas(_ w: Int, _ h: Int) -> CGContext {
	let c = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: cs, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
	c.interpolationQuality = .high
	return c
}
func num(_ v: Any?, _ d: Double) -> Double { (v as? NSNumber)?.doubleValue ?? d }

for p in (spec["plates"] as? [[String: Any]]) ?? [] {
	let name = p["name"] as! String, W = Int(num(p["w"], 1296)), H = Int(num(p["h"], 2304))
	let bg = load(p["bg"] as! String), fg = load(p["fg"] as! String)
	let crop = (p["bgCrop"] as? [NSNumber])?.map { $0.doubleValue } ?? [0, 0, 1]
	let cw = crop[2] * Double(bg.width), ch = cw * Double(H) / Double(W)
	let rect = CGRect(x: crop[0] * Double(bg.width), y: crop[1] * Double(bg.height), width: cw, height: ch)
	if rect.maxX > Double(bg.width) + 1 || rect.maxY > Double(bg.height) + 1 { print("  note: \(name) background crop runs past the picture (\(Int(rect.maxX))x\(Int(rect.maxY)) of \(bg.width)x\(bg.height))") }
	guard let part = bg.cropping(to: rect) else { die("bad crop for \(name)") }
	let b = canvas(W, H)
	b.draw(part, in: CGRect(x: 0, y: 0, width: W, height: H))
	var bgImg = b.makeImage()!
	let blur = num(p["blur"], 0)
	if blur > 0 {
		let ci = CIImage(cgImage: bgImg).clampedToExtent().applyingGaussianBlur(sigma: blur).cropped(to: CGRect(x: 0, y: 0, width: W, height: H))
		bgImg = cictx.createCGImage(ci, from: CGRect(x: 0, y: 0, width: W, height: H), format: .RGBA8, colorSpace: cs)!
	}
	save(bgImg, outDir.appendingPathComponent("\(name).jpg"), jpeg: true)

	let s = num(p["fgScale"], Double(W) / cw)
	let ref = (p["fgRef"] as? [NSNumber])?.map { $0.doubleValue } ?? [crop[0] + crop[2] / 2, (rect.midY) / Double(bg.height)]
	let at = (p["fgAt"] as? [NSNumber])?.map { $0.doubleValue } ?? [0.5, 0.5]
	let fw = Double(fg.width) * s, fh = Double(fg.height) * s
	let left = at[0] * Double(W) - ref[0] * fw, top = at[1] * Double(H) - ref[1] * fh
	let f = canvas(W, H)
	f.draw(fg, in: CGRect(x: left, y: Double(H) - top - fh, width: fw, height: fh))
	if let ext = (p["fgExtend"] as? [NSNumber])?.map({ $0.doubleValue }), ext.count == 2 {   // carry the subject past the picture's side edges by repeating its edge column
		f.interpolationQuality = .none
		if ext[0] > 0, let col = fg.cropping(to: CGRect(x: 0, y: 0, width: 1, height: fg.height)) { f.draw(col, in: CGRect(x: left - ext[0] * s, y: Double(H) - top - fh, width: ext[0] * s + 1, height: fh)) }
		if ext[1] > 0, let col = fg.cropping(to: CGRect(x: fg.width - 1, y: 0, width: 1, height: fg.height)) { f.draw(col, in: CGRect(x: left + fw - 1, y: Double(H) - top - fh, width: ext[1] * s + 1, height: fh)) }
		f.interpolationQuality = .high
	}
	var fgImg = f.makeImage()!
	let sharpen = num(p["sharpen"], 0)
	if sharpen > 0 {
		let ci = CIImage(cgImage: fgImg).applyingFilter("CIUnsharpMask", parameters: ["inputRadius": 2.5, "inputIntensity": sharpen]).cropped(to: CGRect(x: 0, y: 0, width: W, height: H))
		fgImg = cictx.createCGImage(ci, from: CGRect(x: 0, y: 0, width: W, height: H), format: .RGBA8, colorSpace: cs)!
	}
	save(fgImg, outDir.appendingPathComponent("\(name)-fg.png"), jpeg: false)
	let pv = canvas(W, H)
	pv.draw(bgImg, in: CGRect(x: 0, y: 0, width: W, height: H)); pv.draw(fgImg, in: CGRect(x: 0, y: 0, width: W, height: H))
	save(pv.makeImage()!, outDir.appendingPathComponent("\(name)-preview.jpg"), jpeg: true)
	print(String(format: "%@: %dx%d, background x%.2f, subject x%.2f at %.0f,%.0f (%.0fx%.0f)", name, W, H, Double(W) / cw, s, left, top, fw, fh))
}

for st in (spec["stickers"] as? [[String: Any]]) ?? [] {
	let name = st["name"] as! String, fg = load(st["fg"] as! String), maxSide = num(st["max"], 1200)
	let w = fg.width, h = fg.height
	var px = [UInt8](repeating: 0, count: w * h * 4)
	px.withUnsafeMutableBytes { q in
		let c = CGContext(data: q.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4, space: cs, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
		c.draw(fg, in: CGRect(x: 0, y: 0, width: w, height: h))
	}
	var x0 = w, y0 = h, x1 = 0, y1 = 0
	for y in 0..<h { for x in 0..<w where px[(y * w + x) * 4 + 3] > 24 { x0 = min(x0, x); x1 = max(x1, x); y0 = min(y0, y); y1 = max(y1, y) } }
	guard x1 > x0, y1 > y0 else { die("empty sticker \(name)") }
	let m = 6
	x0 = max(0, x0 - m); y0 = max(0, y0 - m); x1 = min(w - 1, x1 + m); y1 = min(h - 1, y1 + m)
	let part = fg.cropping(to: CGRect(x: x0, y: y0, width: x1 - x0 + 1, height: y1 - y0 + 1))!
	let k = min(1.0, maxSide / Double(max(part.width, part.height)))
	let ow = Int(Double(part.width) * k), oh = Int(Double(part.height) * k)
	let c = canvas(ow, oh)
	c.draw(part, in: CGRect(x: 0, y: 0, width: ow, height: oh))
	save(c.makeImage()!, outDir.appendingPathComponent("\(name).png"), jpeg: false)
	print("sticker \(name): \(ow)x\(oh)")
}
