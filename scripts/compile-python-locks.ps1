param(
    [string]$PythonExecutable = "python",
    [switch]$Upgrade
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$pythonVersion = & $PythonExecutable -c "import platform; print(platform.python_version())"
if ($LASTEXITCODE -ne 0) {
    throw "无法执行 Python：$PythonExecutable"
}
if (-not $pythonVersion.StartsWith("3.12.")) {
    throw "锁文件必须使用 Python 3.12 生成，当前版本为 $pythonVersion"
}

$mode = if ($Upgrade) { "--upgrade" } else { "--no-upgrade" }
$env:CUSTOM_COMPILE_COMMAND = "scripts/compile-python-locks.ps1 -PythonExecutable python"
$commonArguments = @(
    "-m",
    "piptools",
    "compile",
    "--generate-hashes",
    "--allow-unsafe",
    "--quiet",
    "--strip-extras",
    "--resolver=backtracking",
    "--newline=lf",
    "--no-emit-index-url",
    "--no-emit-trusted-host",
    $mode
)

function Invoke-LockCompile {
    param(
        [string]$InputFile,
        [string]$OutputFile,
        [string[]]$AdditionalArguments = @()
    )

    & $PythonExecutable @commonArguments @AdditionalArguments $InputFile `
        --output-file $OutputFile
    if ($LASTEXITCODE -ne 0) {
        throw "生成锁文件失败：$OutputFile"
    }
}

Push-Location $repositoryRoot
try {
    Invoke-LockCompile `
        -InputFile "backend/pyproject.toml" `
        -OutputFile "backend/requirements.lock"
    Invoke-LockCompile `
        -InputFile "backend/pyproject.toml" `
        -OutputFile "backend/requirements-dev.lock" `
        -AdditionalArguments @("--extra=dev")
    Invoke-LockCompile `
        -InputFile "agent-worker/pyproject.toml" `
        -OutputFile "agent-worker/requirements.lock"
}
finally {
    Pop-Location
}
