// faces <image>... : prints one line per image: <path>\t<number of faces>\t<largest face area as a share of the frame>
// Uses Apple's Vision framework; nothing leaves this Mac.
import Foundation
import Vision
import AppKit

for path in CommandLine.arguments.dropFirst() {
    var count = 0; var area = 0.0
    if let img = NSImage(contentsOfFile: path), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) {
        let req = VNDetectFaceRectanglesRequest()
        try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
        let faces = req.results ?? []
        count = faces.count
        area = faces.map { Double($0.boundingBox.width * $0.boundingBox.height) }.max() ?? 0
    }
    print("\(path)\t\(count)\t\(String(format: "%.4f", area))")
}
