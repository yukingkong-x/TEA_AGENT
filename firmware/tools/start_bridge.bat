@echo off
chcp 65001 >nul
REM 茶园平台传感器桥接开机自启脚本（队友C）
REM 放到 Windows 启动文件夹，开机自动运行 USB-RS485 桥接

cd /d "D:\soft program\school\competitive\TEA_AGENT\TEA_AGENT\firmware\tools"

:retry
echo [%date% %time%] 尝试启动传感器桥接 (COM11)... >> bridge_autostart.log
python pc_bridge_tea.py COM11 --interval 10 >> bridge_autostart.log 2>&1

REM 如果桥接异常退出（如 COM11 僵死），等 10 秒重试；手动 Ctrl+C 时关窗口即可停止
echo [%date% %time%] 桥接退出，10秒后重试... >> bridge_autostart.log
timeout /t 10 /nobreak >nul
goto retry
