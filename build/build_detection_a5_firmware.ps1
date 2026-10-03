param(
    [ValidatePattern('^[0-9A-Fa-f]{8}$')][string]$BuildId = '0000A501',
    [ValidateSet('detection_a5')][string]$Application = 'detection_a5',
    [string]$CompilerBin = ''
)
$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$bin = if ($CompilerBin) { $CompilerBin } else { Join-Path $root 'build/tools/xpack-riscv-none-elf-gcc-15.2.0-1/bin' }
$BuildId = $BuildId.ToLowerInvariant()
$gcc = Join-Path $bin 'riscv-none-elf-gcc.exe'
$work = Join-Path $root "build/firmware/$BuildId"
[System.IO.Directory]::CreateDirectory($work) | Out-Null
$elf = Join-Path $work 'firmware.elf'
$arguments = @('-march=rv32im','-mabi=ilp32','-O2','-ffreestanding','-fno-builtin',
    '-fno-strict-aliasing','-fdata-sections','-ffunction-sections','-nostdlib','-nostartfiles',
    '-Wl,--gc-sections','-Wl,--build-id=none','-Wall','-Wextra','-Werror',"-DBUILD_ID=0x$BuildId",
    '-T',(Join-Path $root 'src/firmware/link.ld'),"-Wl,-Map=$work/firmware.map",
    '-x','assembler-with-cpp',(Join-Path $root 'src/firmware/start.s'),'-x','c',(Join-Path $root "src/firmware/$Application.c"),'-lgcc','-o',$elf)
& $gcc @arguments
if ($LASTEXITCODE -ne 0) { throw 'Firmware compilation/link failed.' }
& (Join-Path $bin 'riscv-none-elf-objcopy.exe') -O binary $elf (Join-Path $work 'firmware.bin')
if ($LASTEXITCODE -ne 0) { throw 'Firmware binary conversion failed.' }
$disassembly = & (Join-Path $bin 'riscv-none-elf-objdump.exe') -d -M no-aliases $elf
if ($LASTEXITCODE -ne 0) { throw 'Firmware disassembly failed.' }
$disassembly | Set-Content -LiteralPath (Join-Path $work 'firmware.dis') -Encoding ASCII
$attributes = & (Join-Path $bin 'riscv-none-elf-readelf.exe') -A $elf
if ($LASTEXITCODE -ne 0) { throw 'ELF attribute inspection failed.' }
$attributes | Set-Content -LiteralPath (Join-Path $work 'attributes.txt') -Encoding ASCII
$allowed = 'lui auipc jal jalr beq bne blt bge bltu bgeu lb lh lw lbu lhu sb sh sw addi slti sltiu xori ori andi slli srli srai add sub sll slt sltu xor srl sra or and fence ecall ebreak mul mulh mulhsu mulhu div divu rem remu'.Split(' ')
$instructions = @()
foreach ($line in $disassembly) {
    if ($line -match '^\s*[0-9a-f]+:\s+[0-9a-f]{8}\s+([a-z0-9.]+)\s') {
        $mnemonic = $Matches[1]
        if ($allowed -notcontains $mnemonic) { throw "Unexpected instruction in firmware: $mnemonic" }
        $instructions += $mnemonic
    }
}
foreach ($required in @('mul','div','divu','rem','remu','sb','sh','sw','lbu','lhu','lw')) {
    if ($instructions -notcontains $required) { throw "Self-test did not exercise instruction: $required" }
}
[byte[]]$binary = [System.IO.File]::ReadAllBytes((Join-Path $work 'firmware.bin'))
if ($binary.Length -gt 65536) { throw 'Firmware exceeds BRAM capacity.' }
$image = [byte[]]::new(65536)
[Array]::Copy($binary,$image,$binary.Length)
$words = [string[]]::new(16384)
for ($i=0; $i -lt 16384; $i++) { $words[$i] = [BitConverter]::ToUInt32($image,$i*4).ToString('x8') }
[System.IO.File]::WriteAllLines((Join-Path $work 'firmware.hex'),$words,[System.Text.Encoding]::ASCII)
$size = & (Join-Path $bin 'riscv-none-elf-size.exe') $elf
if ($LASTEXITCODE -ne 0) { throw 'Firmware size check failed.' }
$size | Set-Content -LiteralPath (Join-Path $work 'size.txt') -Encoding ASCII
$size
[ordered]@{
    build_id=$BuildId.ToUpperInvariant(); compiler='xPack GCC 15.2.0-1'; isa='rv32im'; abi='ilp32'; optimization='O2'
    binary_bytes=$binary.Length; ram_bytes=65536; source="src/firmware/$Application.c"; application=$Application
    source_sha256=(Get-FileHash -LiteralPath (Join-Path $root "src/firmware/$Application.c") -Algorithm SHA256).Hash.ToLowerInvariant()
    elf_sha256=(Get-FileHash -LiteralPath $elf -Algorithm SHA256).Hash.ToLowerInvariant()
    hex_sha256=(Get-FileHash -LiteralPath (Join-Path $work 'firmware.hex') -Algorithm SHA256).Hash.ToLowerInvariant()
    instructions=($instructions | Sort-Object -Unique)
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $work 'manifest.json') -Encoding UTF8
Write-Output "PASS: RV32IM firmware $BuildId compiled and BRAM image generated."
