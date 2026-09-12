#!/usr/bin/env pwsh

param (
    [Alias("o")]
    [string]$OutputDir = ""
)

$ScriptRoot = Split-Path $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path $ScriptRoot
$EncoderPath = Join-Path $ProjectRoot "src/cpu/encoder"

if ([string]::IsNullOrEmpty($OutputDir)) {
    $OutputDir = $ProjectRoot
}

Push-Location $ProjectRoot
try {
    python -m src.cpu.encoder.main ./src/cpu/encoder/file.de1
    if ($LASTEXITCODE -ne 0) { throw "encoder failed" }

    python -m src.cpu.encoder.utils.bin2hex $EncoderPath/out/file.bin $EncoderPath/out/file.hex
    if ($LASTEXITCODE -ne 0) { throw "bin2hex failed" }

    $ProgramImageSize = (Get-Item $EncoderPath/out/file.bin).Length

    $CpuPkg = Get-Content "$ProjectRoot/hdl/cpu_pkg.sv" -Raw
    if ($CpuPkg -match 'RAM_ADDR_WIDTH\s*=\s*(\d+)') {
        $RamAddrWidth = [int]$Matches[1]
    } else {
        throw "Could not parse RAM_ADDR_WIDTH from hdl/cpu_pkg.sv"
    }
    if ($CpuPkg -match 'USE_INIT_FILE\s*=\s*(\d+)') {
        $UseInitFile = [int]$Matches[1]
    } else {
        throw "Could not parse USE_INIT_FILE from hdl/cpu_pkg.sv"
    }
    $RamDepth = [math]::Pow(2, $RamAddrWidth)

    if ($CpuPkg -match 'localparam\s+int\s+LOADER_MAX_PROGRAM_SIZE\s*=\s*([0-9][0-9_]*)') {
        $LoaderCapacity = [int]($Matches[1] -replace '_', '')
    } else {
        throw "Could not parse literal LOADER_MAX_PROGRAM_SIZE from hdl/cpu_pkg.sv"
    }
    $RuntimeImageSize = $ProgramImageSize + 4
    $RuntimeCapacity = [math]::Min($LoaderCapacity, $RamDepth)
    if ($RuntimeImageSize -gt $RuntimeCapacity) {
        $RuntimeLimitMessage = "Runtime image needs $RuntimeImageSize bytes ($ProgramImageSize encoded + 4-byte halt), but loader/address capacity is $RuntimeCapacity bytes"
        if ($UseInitFile -eq 0) {
            throw $RuntimeLimitMessage
        }
        Write-Warning "$RuntimeLimitMessage. USE_INIT_FILE=1 remains valid; this image cannot be runtime-loaded."
    }

    $RomWordDepth = [int]($RamDepth / 4)
    Write-Host "[INFO] RAM_ADDR_WIDTH=$RamAddrWidth → byte depth=$RamDepth, word depth=$RomWordDepth"

    python -m src.cpu.encoder.utils.hex_to_mif $EncoderPath/out/file.hex "$OutputDir/file.mif" --width 32 --depth $RomWordDepth
    if ($LASTEXITCODE -ne 0) { throw "hex_to_mif failed" }

    python -m src.cpu.encoder.utils.hex_to_mif $EncoderPath/out/file.hex "$OutputDir/data.mif" --width 8 --depth $RamDepth
    if ($LASTEXITCODE -ne 0) { throw "hex_to_mif (data) failed" }
}
finally {
    Pop-Location
}

Copy-Item "$EncoderPath/out/file.hex" "$ProjectRoot/file.hex"
$ProgramSizeHeader = "localparam int PROGRAM_IMAGE_SIZE = $ProgramImageSize;`n"
[IO.File]::WriteAllText(
    (Join-Path $ProjectRoot "program_size.svh"),
    $ProgramSizeHeader,
    [Text.UTF8Encoding]::new($false)
)

Write-Host ""
Write-Host "[INFO] Program encoded successfully!" -ForegroundColor Green
Write-Host "[INFO] Files generated:" -ForegroundColor Cyan
Write-Host "  - file.hex                            (for loader.sv)" -ForegroundColor White
Write-Host "  - program_size.svh                    (loader image size)" -ForegroundColor White
Write-Host "  - file.mif                            (for FPGA instruction ROM)" -ForegroundColor White
Write-Host "  - data.mif                            (for FPGA data RAM)" -ForegroundColor White
Write-Host "[INFO] file.mif and data.mif are automatically used by Quartus during synthesis" -ForegroundColor Yellow
