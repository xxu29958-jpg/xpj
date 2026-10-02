import XCTest
import UIKit
import UniformTypeIdentifiers
final class ShortcutProbe: XCTestCase {
    @MainActor func testSystemFileUploadPersistsAndReturnsReceipt() {
        continueAfterFailure = false
        let app = XCUIApplication(bundleIdentifier: "com.apple.shortcuts")
        // Keep the system app and its action catalog alive from the environment step.
        app.activate()
        XCTAssertEqual(app.state, .runningForeground)
        print("SHORTCUTS_UI_TREE_BEGIN\n\(app.debugDescription)\nSHORTCUTS_UI_TREE_END")
        let create = app.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "Create Shortcut", "add")).firstMatch
        XCTAssertTrue(create.waitForExistence(timeout: 10))
        create.tap()
        XCTAssertEqual(app.state, .runningForeground)
        print("SHORTCUTS_EDITOR_UI_TREE_BEGIN\n\(app.debugDescription)\nSHORTCUTS_EDITOR_UI_TREE_END")
        let web = app.buttons["Web"]
        XCTAssertTrue(web.waitForExistence(timeout: 10))
        let categories = app.scrollViews.containing(.button, identifier: "Web").firstMatch
        for _ in 0..<4 {
            if web.isHittable { break }
            categories.swipeLeft()
        }
        XCTAssertTrue(web.isHittable)
        web.tap()
        let action = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Get Contents of URL")).firstMatch
        // A fresh simulator starts its full ToolKit index after the editor is already visible.
        // Wait for the real action, not merely the app or category to be present.
        let foundAction = action.waitForExistence(timeout: 240)
        print("SHORTCUTS_WEB_CATEGORY_UI_TREE_BEGIN\n\(app.debugDescription)\nSHORTCUTS_WEB_CATEGORY_UI_TREE_END")
        let categoryTree = XCTAttachment(string: app.debugDescription)
        categoryTree.name = "Observed Web action category"
        categoryTree.lifetime = .keepAlways
        add(categoryTree)
        let categoryScreen = XCTAttachment(screenshot: app.screenshot())
        categoryScreen.name = "Observed Web action category"
        categoryScreen.lifetime = .keepAlways
        add(categoryScreen)
        XCTAssertTrue(foundAction)
        action.tap()
        print("SHORTCUTS_URL_ACTION_UI_TREE_BEGIN\n\(app.debugDescription)\nSHORTCUTS_URL_ACTION_UI_TREE_END")
        let tree = XCTAttachment(string: app.debugDescription)
        tree.name = "URL action editor accessibility tree"
        tree.lifetime = .keepAlways
        add(tree)
        let screen = XCTAttachment(screenshot: app.screenshot())
        screen.name = "URL action added through XCTest"
        screen.lifetime = .keepAlways
        add(screen)
        let request = app.otherElements.matching(NSPredicate(format: "label == %@", "Get contents of , URL")).firstMatch
        XCTAssertTrue(request.waitForExistence(timeout: 10))
        // The system's accessibility element groups the URL chip and disclosure control.
        // This point is the blue disclosure in the captured iPhone 17 Pro action row.
        request.coordinate(withNormalizedOffset: CGVector(dx: 0.725, dy: 0.5)).tap()
        let optionsTree = XCTAttachment(string: app.debugDescription)
        optionsTree.name = "URL request options accessibility tree"
        optionsTree.lifetime = .keepAlways
        add(optionsTree)
        let optionsScreen = XCTAttachment(screenshot: app.screenshot())
        optionsScreen.name = "URL request options"
        optionsScreen.lifetime = .keepAlways
        add(optionsScreen)
        XCTAssertTrue(app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "Method")).firstMatch.waitForExistence(timeout: 10))
        app.buttons["GET"].tap()
        let post = app.buttons["POST"]
        XCTAssertTrue(post.waitForExistence(timeout: 10))
        post.tap()
        let postTree = XCTAttachment(string: app.debugDescription)
        postTree.name = "POST request body choices accessibility tree"
        postTree.lifetime = .keepAlways
        add(postTree)
        let bodyType = app.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "JSON", "Form")).firstMatch
        XCTAssertTrue(bodyType.waitForExistence(timeout: 10))
        bodyType.tap()
        let file = app.buttons["File"]
        XCTAssertTrue(file.waitForExistence(timeout: 10))
        file.tap()
        XCTAssertTrue(app.buttons["POST"].exists)
        XCTAssertTrue(app.buttons["File"].exists)
        let fileTree = XCTAttachment(string: app.debugDescription)
        fileTree.name = "POST file request accessibility tree"
        fileTree.lifetime = .keepAlways
        add(fileTree)
        let fileScreen = XCTAttachment(screenshot: app.screenshot())
        fileScreen.name = "POST file request configured through the system UI"
        fileScreen.lifetime = .keepAlways
        add(fileScreen)
        app.buttons["Choose Variable"].tap()
        let inputTree = XCTAttachment(string: app.debugDescription)
        inputTree.name = "Available system file inputs"
        inputTree.lifetime = .keepAlways
        add(inputTree)
        let inputScreen = XCTAttachment(screenshot: app.screenshot())
        inputScreen.name = "Available system file inputs"
        inputScreen.lifetime = .keepAlways
        add(inputScreen)
        app.buttons["Clipboard"].tap()
        // The URL chip is inside the observed merged action row.
        request.coordinate(withNormalizedOffset: CGVector(dx: 0.595, dy: 0.5)).tap()
        let fields = app.descendants(matching: .any).matching(NSPredicate(
            format: "elementType == %d OR elementType == %d",
            XCUIElement.ElementType.textField.rawValue, XCUIElement.ElementType.textView.rawValue))
        let field = fields.firstMatch
        let fieldExists = field.waitForExistence(timeout: 10)
        captureText(app, "URL input before configuration")
        XCTAssertTrue(fieldExists)
        let url = ProcessInfo.processInfo.environment["TICKETBOX_TEST_UPLOAD_URL"]!
        field.typeText(url + "\n")
        captureText(app, "URL configured for the isolated upload")
        let jpeg = Data(base64Encoded: ProcessInfo.processInfo.environment["TICKETBOX_TEST_IMAGE"]!)!
        UIPasteboard.general.setData(jpeg, forPasteboardType: UTType.jpeg.identifier)
        let play = app.buttons["play"]
        XCTAssertTrue(play.waitForExistence(timeout: 10))
        XCTAssertTrue(play.isHittable)
        play.tap()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let deadline = Date().addingTimeInterval(60)
        var receiptVisible = false
        while Date() < deadline {
            for surface in [app, springboard] {
                for label in ["Allow Paste", "Allow Once", "Allow"] {
                    let permission = surface.alerts.buttons[label]
                    if permission.exists && permission.isHittable { permission.tap() }
                }
            }
            let state = app.debugDescription
            if state.contains("uploaded") && state.contains("public_id") {
                receiptVisible = true
                break
            }
            RunLoop.current.run(until: Date().addingTimeInterval(1))
        }
        captureText(app, "Actual upload result in Shortcuts")
        XCTAssertTrue(receiptVisible, "The actual system action must expose the upload receipt")
    }

    @MainActor private func captureText(_ app: XCUIApplication, _ name: String) {
        // Raw attachments stay private. The host exports only text with the upload key removed.
        let attachment = XCTAttachment(string: app.debugDescription)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
