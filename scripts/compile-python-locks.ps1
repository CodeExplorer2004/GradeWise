param(
    [string]$PythonExecutable = "python",
    [switch]$Upgrade
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$mode = if ($Upgrade) { "--upgrade" } else { "--no-upgrade" }
$compileCommand = "scripts/compile-python-locks.ps1 -PythonExecutable python"

if ($env:OS -eq "Windows_NT") {
    $containerScript = @(
        "set -eu",
        'python -m pip install --disable-pip-version-check --root-user-action=ignore --quiet "pip-tools==7.5.3"',
        "python -m piptools compile --generate-hashes --allow-unsafe --quiet --strip-extras --resolver=backtracking --newline=lf --no-emit-index-url --no-emit-trusted-host $mode backend/pyproject.toml --output-file backend/requirements.lock",
        "python -m piptools compile --generate-hashes --allow-unsafe --quiet --strip-extras --resolver=backtracking --newline=lf --no-emit-index-url --no-emit-trusted-host $mode --extra=dev backend/pyproject.toml --output-file backend/requirements-dev.lock",
        "python -m piptools compile --generate-hashes --allow-unsafe --quiet --strip-extras --resolver=backtracking --newline=lf --no-emit-index-url --no-emit-trusted-host $mode agent-worker/pyproject.toml --output-file agent-worker/requirements.lock"
    ) -join "`n"

    Push-Location $repositoryRoot
    try {
        & docker run --rm `
            --mount "type=bind,source=$repositoryRoot,target=/workspace" `
            --workdir /workspace `
            --env "CUSTOM_COMPILE_COMMAND=$compileCommand" `
            python:3.12-slim sh -c $containerScript
        if ($LASTEXITCODE -ne 0) {
            throw "在 Linux Python 3.12 容器中生成锁文件失败"
        }
    }
    finally {
        Pop-Location
    }
    return
}

$pythonVersion = & $PythonExecutable -c "import platform; print(platform.python_version())"
if ($LASTEXITCODE -ne 0) {
    throw "无法执行 Python：$PythonExecutable"
}
if (-not $pythonVersion.StartsWith("3.12.")) {
    throw "锁文件必须使用 Python 3.12 生成，当前版本为 $pythonVersion"
}

$env:CUSTOM_COMPILE_COMMAND = $compileCommand
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
