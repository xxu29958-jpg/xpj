import XCTest
import UIKit
import UniformTypeIdentifiers
final class ShortcutProbe: XCTestCase {
    @MainActor func testPhotosLibraryBecomesUsable() throws {
        continueAfterFailure = false
        let photos = XCUIApplication(bundleIdentifier: "com.apple.mobileslideshow")
        photos.activate()
        captureText(photos, "Photos before library readiness")
        let deadline = Date().addingTimeInterval(180)
        let library = photos.buttons["Library"]
        // The library is already in the accessibility tree behind What's New.
        // Only a hittable tab proves the introduction no longer covers it.
        while Date() < deadline && !(library.exists && library.isHittable) {
            let introduction = photos.buttons["Continue"]
            if introduction.exists && introduction.isHittable {
                captureText(photos, "Photos introduction")
                introduction.tap()
            }
            RunLoop.current.run(until: Date().addingTimeInterval(1))
        }
        captureText(photos, "Photos after waiting for its library")
        let screen = XCTAttachment(screenshot: photos.screenshot())
        screen.name = "Photos library readiness before credentials exist"
        screen.lifetime = .keepAlways
        add(screen)
        XCTAssertTrue(library.exists && library.isHittable, "Photos must expose its real library before media import")
        library.tap()
    }

    @MainActor func testSystemFileUploadPersistsAndReturnsReceipt() throws {
        continueAfterFailure = false
        let environment = ProcessInfo.processInfo.environment
        let url = try XCTUnwrap(environment["TICKETBOX_TEST_UPLOAD_URL"], "Missing isolated upload input")
        let imageInput = try XCTUnwrap(environment["TICKETBOX_TEST_IMAGE"], "Missing receipt image input")
        let jpeg = try XCTUnwrap(Data(base64Encoded: imageInput), "Invalid receipt image input")
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
        let search = app.searchFields["Search Actions"]
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        search.tap()
        search.typeText("Get Contents of URL")
        let action = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Get Contents of URL")).firstMatch
        // A fresh simulator starts its full ToolKit index after the editor is already visible.
        // Wait for the real action, not merely the app or category to be present.
        let foundAction = action.waitForExistence(timeout: 240)
        print("SHORTCUTS_ACTION_SEARCH_UI_TREE_BEGIN\n\(app.debugDescription)\nSHORTCUTS_ACTION_SEARCH_UI_TREE_END")
        let categoryTree = XCTAttachment(string: app.debugDescription)
        categoryTree.name = "Observed exact action search"
        categoryTree.lifetime = .keepAlways
        add(categoryTree)
        let categoryScreen = XCTAttachment(screenshot: app.screenshot())
        categoryScreen.name = "Observed exact action search"
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
        // This token editor exposes a focused URL keyboard, not a TextField/TextView AX node.
        let keyboard = app.keyboards.firstMatch
        // An observed first tap left the token unchanged after choosing Clipboard.
        // Retry that same harmless selection only while its keyboard is absent.
        for _ in 0..<2 {
            request.coordinate(withNormalizedOffset: CGVector(dx: 0.595, dy: 0.5)).tap()
            if keyboard.waitForExistence(timeout: 5) { break }
        }
        captureText(app, "URL input before configuration")
        XCTAssertTrue(keyboard.exists)
        // The system token editor does not expose keyboard focus to XCTest typing.
        // Paste through its native editing menu, as an Owner pastes the full UploadLink.
        UIPasteboard.general.string = url
        request.coordinate(withNormalizedOffset: CGVector(dx: 0.595, dy: 0.5)).press(forDuration: 1.2)
        let paste = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Paste")).firstMatch
        let pasteExists = paste.waitForExistence(timeout: 10)
        captureText(app, "System paste menu for the upload address")
        XCTAssertTrue(pasteExists)
        paste.tap()
        let pastePermission = app.alerts.buttons["Allow Paste"]
        if pastePermission.waitForExistence(timeout: 3) { pastePermission.tap() }
        keyboard.buttons["Done"].tap()
        captureText(app, "URL configured for the isolated upload")
        XCTAssertTrue(app.debugDescription.contains(url))
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
                    // Shortcuts can render consent in a sheet rather than an AX Alert.
                    let permission = surface.buttons[label]
                    if permission.exists && permission.isHittable {
                        captureText(surface, "System consent before upload")
                        permission.tap()
                    }
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
        captureText(springboard, "System surface after the upload attempt")
        XCTAssertTrue(receiptVisible, "The actual system action must expose the upload receipt")
        try inspectPhotosShareEntry(app)
    }

    @MainActor private func inspectPhotosShareEntry(_ app: XCUIApplication) throws {
        // Public Details UI documented by Apple; the info control was observed in this editor.
        let info = app.buttons["info"]
        XCTAssertTrue(info.waitForExistence(timeout: 10))
        info.tap()
        captureText(app, "Shortcut sharing details before enabling")
        let sharing = app.switches["Show in Share Sheet"]
        XCTAssertTrue(sharing.waitForExistence(timeout: 10))
        if sharing.value as? String != "1" {
            // The observed labelled AX row contains a separate switch control.
            // Tapping the row's label leaves its value unchanged.
            let toggle = sharing.switches.firstMatch
            XCTAssertTrue(toggle.waitForExistence(timeout: 5))
            XCTAssertTrue(toggle.isHittable)
            toggle.tap()
        }
        captureText(app, "Shortcut sharing details enabled")
        XCTAssertEqual(sharing.value as? String, "1")
        app.buttons["Done"].tap()
        app.buttons["Back"].tap()
        let photos = XCUIApplication(bundleIdentifier: "com.apple.mobileslideshow")
        photos.launch()
        captureText(photos, "System Photos entry for shortcut discovery")
        for _ in 0..<2 {
            let introduction = photos.buttons["Continue"]
            if introduction.exists && introduction.isHittable { introduction.tap() } else { break }
        }
        let library = photos.buttons["Library"]
        if library.exists && library.isHittable { library.tap() }
        let libraryPhotos = photos.images.matching(NSPredicate(format: "label BEGINSWITH %@", "Photo,"))
        let deadline = Date().addingTimeInterval(10)
        var visiblePhoto: XCUIElement?
        while Date() < deadline {
            visiblePhoto = libraryPhotos.allElementsBoundByIndex.first { $0.isHittable }
            if visiblePhoto != nil { break }
            RunLoop.current.run(until: Date().addingTimeInterval(0.5))
        }
        captureText(photos, "Simulator Photos library for shortcut discovery")
        // Photos is foreground and contains only the simulator's stock library, never the upload URL.
        let libraryImage = XCTAttachment(screenshot: photos.screenshot())
        libraryImage.name = "Simulator Photos library for shortcut discovery"
        libraryImage.lifetime = .keepAlways
        add(libraryImage)
        let photo = try XCTUnwrap(visiblePhoto, "A visible simulator photo must be selectable")
        photo.tap()
        let share = photos.buttons["Share"]
        XCTAssertTrue(share.waitForExistence(timeout: 10))
        share.tap()
        let shortcut = photos.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Get Contents of URL")).firstMatch
        for _ in 0..<3 {
            if shortcut.exists && shortcut.isHittable { break }
            photos.swipeUp()
        }
        captureText(photos, "Configured shortcut in the Photos share sheet")
        XCTAssertTrue(shortcut.exists && shortcut.isHittable)
        // Entry discovery only: its body still uses Clipboard. Do not run or claim the share-input journey yet.
    }

    @MainActor private func captureText(_ app: XCUIApplication, _ name: String) {
        // Raw attachments stay private. The host exports only text with the upload key removed.
        let attachment = XCTAttachment(string: app.debugDescription)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
