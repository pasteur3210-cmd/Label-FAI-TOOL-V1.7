# Label Inspection Tool V1.9.23 Release Notes

This release targets the GRG-4297u Carton Label field test and operator-review usability.

## Identity correction
The supplied Carton Label Request Form contains two different part numbers under Finished Information: blank stock `502109-020` and finished Carton Label `680010-354`. V1.9.23 treats these as different concepts and uses `680010-354` as Profile Label P/N. The document title identifies the label family as `Carton Label`, while the Model field remains `GRG-4297u`.

## Operator UI
The Image Label Inspection screen uses a more compact Manual Review section so the bottom result table is visible on normal Windows work areas. The Manual Review popup enlarges the content an operator is actually comparing: Item, Actual, Expected and Golden specification.

## Compatibility
Legacy CAM/Image engines, Dynamic Golden completeness, Barcode/QR paths, production S/N/MAC rules, Manual Review traceability and record path-length protection remain under the existing regression suite.

## Build
Use GitHub Actions with Python 3.11. The workflow performs cleanup, Release Gate, Integration Gate, Ruff F821, compile, unit tests, PyInstaller and packaged EXE smoke tests.
