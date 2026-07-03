@echo off
chcp 65001 >nul
title 多源勘察数据联动展示与证据链追溯系统
cd /d "%~dp0"

echo ============================================================
echo   多源勘察数据联动展示与证据链追溯系统
echo   Multi-source Survey Data Fusion ^& Evidence-Chain Platform
echo ============================================================
echo.

REM ---- 检查 Python ----
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+ 并加入 PATH。
    pause
    exit /b 1
)

REM ---- 检查并安装依赖 ----
python -c "import fastapi, uvicorn, numpy, pandas, matplotlib, PIL, sklearn, docx" >nul 2>nul
if errorlevel 1 (
    echo [1/3] 正在安装 Python 依赖（首次运行需要，约 30 秒）...
    python -m pip install fastapi uvicorn numpy pandas matplotlib pillow scikit-learn python-docx --quiet
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动执行：pip install fastapi uvicorn numpy pandas matplotlib pillow scikit-learn python-docx
        pause
        exit /b 1
    )
) else (
    echo [1/3] Python 依赖已就绪 ✓
)

REM ---- 检查数据是否已生成 ----
if not exist "backend\data\manifest.json" (
    echo [2/3] 首次运行，正在生成多源勘察样例数据...
    python backend\generate_data.py
    if errorlevel 1 (
        echo [错误] 数据生成失败。
        pause
        exit /b 1
    )
) else (
    echo [2/3] 勘察数据已就绪 ✓
)

REM ---- 启动服务 ----
echo [3/3] 启动 Web 服务...
echo.
echo ============================================================
echo   ✓ 系统已启动！
echo.
echo   请在浏览器打开： http://localhost:8000
echo.
echo   关闭本窗口即可停止服务。
echo   如需重新生成数据，删除 backend\data 文件夹后再次运行。
echo ============================================================
echo.

REM 延迟 2 秒后自动打开浏览器
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
pause
