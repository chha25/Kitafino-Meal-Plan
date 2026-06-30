@echo off
setlocal

echo == Python discovery ==
where python
if errorlevel 1 echo python not found on PATH
where py
if errorlevel 1 echo py launcher not found on PATH

echo.
echo == Python version ==
python --version
if errorlevel 1 (
  echo python --version failed
) else (
  python -c "import sys; print(sys.executable); print(sys.version)"
)

echo.
echo == Pytest ==
python -m pytest
exit /b %errorlevel%
