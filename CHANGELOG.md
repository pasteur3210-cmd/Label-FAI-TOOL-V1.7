# Change Log

## V1.9.23 - 2026-09-03

### Fixed
- Carton Label import no longer selects `Blank Label Part Number` as the production Label P/N.
- Explicit `Carton Label Part Number` is prioritized; supplied form resolves to `680010-354`.
- Carton Request Forms now classify as `Carton Label`.
- Dynamic Profile canonical identity keeps Internal Model separate from Label Type and removes accidental trailing label-family descriptors from the model.
- Image inspection main screen reserves more vertical space for the Inspection Item result table.
- Manual Review gives larger visual priority to Inspection Item, Actual, Expected and Golden Item Specification.

### Packaging
- Release folder/artifact naming is shortened to `Label_Inspection_Tool_V1.9.23`.
- Modification descriptions are kept in Markdown instead of long folder names.
