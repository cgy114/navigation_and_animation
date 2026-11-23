@echo off
setlocal
cd /d "%~dp0"

set "BIN=%KEIL_BIN%"
if not defined BIN set "BIN=D:\Keil_v5\ARM\ARMCLANG\bin"
if not exist "%BIN%\armclang.exe" if not defined KEIL_BIN set "BIN=C:\Keil_v5\ARM\ARMCLANG\bin"
if not exist "%BIN%\armclang.exe" (
  echo [ERROR] armclang not found. Set KEIL_BIN to the ARMCLANG bin directory.
  if /I not "%~1"=="--no-pause" pause
  exit /b 1
)

set "PROJ=%~dp0.."
set "SRC=%~dp0..\..\source"
set INC=-I"%PROJ%" -I"%PROJ%\hardware" -I"%PROJ%\middle" -I"%PROJ%\app" -I"%SRC%" -I"%SRC%\third_party\CMSIS\Core\Include"
set CFLAGS=--target=arm-arm-none-eabi -mcpu=cortex-m0plus -D__MSPM0G3507__ -O2 -fshort-wchar -fshort-enums -c

if not exist Objects mkdir Objects

echo === compile ===
call :cc "%PROJ%\car_main.c" car_main || goto failed
call :cc "%PROJ%\ti_msp_dl_config.c" ti_msp_dl_config || goto failed
call :cc "%PROJ%\hardware\uart_imu.c" uart_imu || goto failed
call :cc "%PROJ%\hardware\uart_pi.c" uart_pi || goto failed
call :cc "%PROJ%\hardware\encoder.c" encoder || goto failed
call :cc "%PROJ%\hardware\motor.c" motor || goto failed
call :cc "%PROJ%\hardware\oled.c" oled || goto failed
call :cc "%PROJ%\hardware\servo.c" servo || goto failed
call :cc "%PROJ%\hardware\battery.c" battery || goto failed
call :cc "%PROJ%\middle\mid_debug_uart.c" mid_debug_uart || goto failed
call :cc "%PROJ%\middle\mid_timer.c" mid_timer || goto failed
call :cc "%PROJ%\middle\pid.c" pid || goto failed
call :cc "%PROJ%\app\odometry.c" odometry || goto failed
call :cc "%PROJ%\app\motion.c" motion || goto failed
call :cc "%PROJ%\app\command.c" command || goto failed
call :cc "%PROJ%\app\pid_store.c" pid_store || goto failed

echo compile startup...
"%BIN%\armasm.exe" --cpu Cortex-M0+ --pd "__MICROLIB SETA 1" -o Objects\startup_mspm0g350x_uvision.o startup_mspm0g350x_uvision.s || goto failed

:link
echo === link ===
"%BIN%\armlink.exe" --cpu Cortex-M0+ Objects\car_main.o Objects\startup_mspm0g350x_uvision.o Objects\ti_msp_dl_config.o Objects\uart_imu.o Objects\uart_pi.o Objects\encoder.o Objects\motor.o Objects\oled.o Objects\servo.o Objects\battery.o Objects\mid_debug_uart.o Objects\mid_timer.o Objects\pid.o Objects\odometry.o Objects\motion.o Objects\command.o Objects\pid_store.o --library_type=microlib --strict --scatter ./mspm0g3507.sct "%SRC%\ti\driverlib\lib\keil\m0p\mspm0g1x0x_g3x0x\driverlib.a" --info sizes --info totals --list .\smart_car.map -o .\Objects\smart_car.axf
if errorlevel 1 goto failed

echo === hex ===
"%BIN%\fromelf.exe" --i32combined Objects\smart_car.axf -o Objects\smart_car.hex
if errorlevel 1 goto failed

set "PYEXE=python"
where python >nul 2>&1 || set "PYEXE=C:\Users\21415\AppData\Local\Programs\Python\Python314\python.exe"
if exist "%~dp0..\..\..\..\pad_hex.py" (
  "%PYEXE%" "%~dp0..\..\..\..\pad_hex.py" "Objects\smart_car.hex"
  if errorlevel 1 goto failed
)

echo.
echo [DONE] Objects\smart_car.hex
dir /b Objects\smart_car.hex
if /I not "%~1"=="--no-pause" pause
exit /b 0

:cc
"%BIN%\armclang.exe" %CFLAGS% %INC% "%~1" -o "Objects\%~2.o"
if errorlevel 1 (
  echo [FAIL] %~2
  exit /b 1
)
exit /b 0

:failed
echo.
echo [FAILED] build error
if /I not "%~1"=="--no-pause" pause
exit /b 1
