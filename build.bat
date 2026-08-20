@echo off
setlocal
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist release_logs mkdir release_logs
python -m compileall -q label_tool tests
if errorlevel 1 exit /b 1
python -m unittest discover -s tests -v > release_logs\test_log.txt 2>&1
type release_logs\test_log.txt
if errorlevel 1 exit /b 1
pyinstaller --noconfirm build.spec
if errorlevel 1 exit /b 1
if not exist dist\Label_Inspection_Tool\profiles mkdir dist\Label_Inspection_Tool\profiles
copy /Y label_tool\profiles\*.json dist\Label_Inspection_Tool\profiles\ >nul
echo Build completed.
endlocal

@echo Running packaged OCR runtime smoke test...
"dist\Label_Inspection_Tool\Label_Inspection_Tool.exe" --self-test-ocr --self-test-output "release_logs\exe_ocr_smoke.json"
@if errorlevel 1 exit /b %errorlevel%
