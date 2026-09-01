param(
    [switch]$Run
)

# Create the project virtual environment, install PAVE, and optionally launch
# the graphical editor. Requires Python 3.10+ and the Python launcher or python
# executable on PATH.

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $RootDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
$PyCommand = Get-Command python -ErrorAction SilentlyContinue

if ($PyLauncher) {
    $PythonArgs = @("-3")
    $PythonExecutable = $PyLauncher.Source
} elseif ($PyCommand) {
    $PythonArgs = @()
    $PythonExecutable = $PyCommand.Source
} else {
    throw "Python 3.10 or newer is required but was not found."
}

& $PythonExecutable @PythonArgs -c "import sys; sys.exit('Python 3.10+ is required') if sys.version_info < (3, 10) else None"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment: $VenvDir"
    & $PythonExecutable @PythonArgs -m venv $VenvDir
}

& $VenvPython -c "import sys; sys.exit('The existing .venv must use Python 3.10+') if sys.version_info < (3, 10) else None"

Write-Host "Installing PAVE and its dependencies..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e $RootDir

Write-Host "Installation complete. Activate with:"
Write-Host "  .\.venv\Scripts\Activate.ps1"

if ($Run) {
    Write-Host "Launching the PAVE editor..."
    & $VenvPython -m terrain_generator.cli --edit --output (Join-Path $RootDir "generated\editor")
    exit $LASTEXITCODE
}

Write-Host "Launch the editor with:"
Write-Host "  .\.venv\Scripts\python.exe -m terrain_generator.cli --edit --output generated\editor"
