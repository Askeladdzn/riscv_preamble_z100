param([ValidateSet('selector','unit','system')][string]$Mode='system', [string]$Python='python', [string]$VivadoBin='E:/Xilinx/Vivado/2023.1/bin')
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python=$Python
$bin=$VivadoBin
if($Mode -eq 'selector') {
    & $python -B -X utf8 (Join-Path $root 'src/host/detection_a5.py') prepare-selector
    $work=Join-Path $root 'sim/work/selector_a5'
    $names=@('src/rtl/peak_selector.v','sim/tb_peak_selector.sv')
    $top='tb_peak_selector'
} elseif($Mode -eq 'unit') {
    & $python -B -X utf8 (Join-Path $root 'src/host/detection_a5.py') prepare-unit
    $work=Join-Path $root 'sim/work/window_a5'
    $names=@('src/rtl/peak_selector.v','src/rtl/window_multi_accel.v','sim/tb_window_multi_accel.sv')
    $top='tb_window_multi_accel'
} else {
    & $python -B -X utf8 (Join-Path $root 'src/host/detection_a5.py') prepare-sim
    $work=Join-Path $root 'sim/work/detection_0000a501'
    Copy-Item -LiteralPath (Join-Path $root 'build/firmware/0000a501/firmware.hex') -Destination (Join-Path $work 'firmware.hex')
    $names=@('src/third_party/picorv32/picorv32.v','src/rtl/uart_rx.v','src/rtl/uart_tx.v','src/rtl/dot_accel.v',
        'src/rtl/peak_selector.v','src/rtl/window_multi_accel.v','src/rtl/riscv_multi_soc.v','sim/tb_detection_a5_system.sv')
    $top='tb_detection_a5_system'
}
if($LASTEXITCODE -ne 0) { throw 'Vector preparation failed' }
$sources=@($names | ForEach-Object { Join-Path $root $_ })
Push-Location -LiteralPath $work
try {
    & (Join-Path $bin 'xvlog.bat') --sv @sources
    if($LASTEXITCODE -ne 0) { throw 'Compilation failed' }
    & (Join-Path $bin 'xelab.bat') $top -s a5_sim --timescale 1ns/1ps
    if($LASTEXITCODE -ne 0) { throw 'Elaboration failed' }
    $log=Join-Path $root "sim/results/detection_a5_$Mode.log"
    if(Test-Path -LiteralPath $log) { Copy-Item -LiteralPath $log -Destination "$log.$(Get-Date -Format yyyyMMdd_HHmmss).previous" }
    & (Join-Path $bin 'xsim.bat') a5_sim -runall -log $log
    if($LASTEXITCODE -ne 0) { throw 'Simulation failed' }
    $result=Get-Content -LiteralPath $log -Raw
    if($result -match 'FAIL:' -or $result -notmatch 'PASS:') { throw 'No clean PASS' }
    $archive=Join-Path $root "sim/results/detection_a5_$Mode"
    [IO.Directory]::CreateDirectory($archive) | Out-Null
    if($Mode -eq 'system') {
        & $python -B -X utf8 (Join-Path $root 'src/host/detection_a5.py') verify-sim
        if($LASTEXITCODE -ne 0) { throw 'Reference verification failed' }
        $files=@('plan.json','responses.jsonl','verified_cases.json','summary.json')
    } else { $files=@('oracle.json') }
    foreach($file in $files) { Copy-Item -LiteralPath (Join-Path $work $file) -Destination (Join-Path $archive $file) }
} finally { Pop-Location }
