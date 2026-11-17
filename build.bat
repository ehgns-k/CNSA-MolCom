@echo off
rem 단일 실행 파일(dist\MolCom.exe)을 만든다.
python -m pip install -r requirements.txt pyinstaller || exit /b 1
python -m PyInstaller --noconfirm --onefile --windowed --name MolCom ^
    --hidden-import pystray._win32 ^
    --add-data "models\face_detection_yunet_2023mar.onnx;models" ^
    --add-data "models\face_recognition_sface_2021dec.onnx;models" main.pyw || exit /b 1
