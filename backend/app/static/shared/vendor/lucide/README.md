# Lucide icons

Selected, unmodified icon geometry from lucide-static 1.51.0 (ISC).
Source: https://github.com/lucide-icons/lucide and https://registry.npmjs.org/lucide-static/-/lucide-static-1.51.0.tgz

The package SHA-512 was verified before extracting the selected icons into SVG symbols.
Integrity: `sha512-ts58ApMc5w5SHHUJBtGO+mgf9lo79FApQ1LttKQoJiMrWNZt8zxWA7R6owK6DoGA3XLjJXc/7rDJh1feonl79g==`

To rebuild, read `package/icons/<symbol-id>.svg` for each symbol in icons.svg, retain the source viewBox and stroke attributes, and wrap its child elements in a symbol with that id.
No package scripts or runtime dependency are used. See LICENSE for the upstream notices.

The primary navigation and settings entry icons also ship as Android VectorDrawable resources
(`ic_lucide_*`). Their paths retain the same 24-unit viewport, 2-unit rounded stroke
and geometry; SVG circles, polylines and rounded rectangles are expressed as paths.
The Android assets include the same upstream license. Navigation behavior and
responsive layout remain owned by each client's existing navigation components.
