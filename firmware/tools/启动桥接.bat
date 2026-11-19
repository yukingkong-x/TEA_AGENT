@echo off
chcp 65001 >nul
title 茶园传感器桥接
cd /d "D:\soft program\school\competitive\TEA_AGENT\TEA_AGENT\firmware\tools"

echo ============================================
echo   茶园平台 USB-RS485 传感器桥接
echo ============================================
echo.
echo 启动前请确认：USB-RS485 转换器已插好（COM11）
echo.

:check
echo [%time%] 正在启动桥接...
python pc_bridge_tea.py COM11 --interval 10

echo.
echo [%time%] 桥接已停止。
echo 若提示"拒绝访问/设备没有发挥作用"，请重新插拔 USB-RS485 后重试。
echo.
pause
