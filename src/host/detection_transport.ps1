param(
    [Parameter(Mandatory=$true)][string]$Port,
    [Parameter(Mandatory=$true)][string]$Plan,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference='Stop'
$items=Get-Content -LiteralPath $Plan -Raw | ConvertFrom-Json
[System.IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$writer=[System.IO.StreamWriter]::new((Join-Path $OutputDirectory 'responses.jsonl'),$false,[System.Text.UTF8Encoding]::new($false))
$serial=[System.IO.Ports.SerialPort]::new($Port,115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
$serial.Handshake=[System.IO.Ports.Handshake]::None
$serial.DtrEnable=$false
$serial.RtsEnable=$false
$serial.ReadTimeout=5000
$serial.WriteTimeout=5000
$serial.ReadBufferSize=65536
$failure=$null
$finished=0
function Read-Bytes([int]$Count) {
    $data=[byte[]]::new($Count)
    $offset=0
    while ($offset -lt $Count) { $offset += $serial.Read($data,$offset,$Count-$offset) }
    return ,$data
}
try {
    $serial.Open()
    $serial.DiscardInBuffer()
    $serial.DiscardOutBuffer()
    foreach($item in $items) {
        $tx=[byte[]]::new($item.tx_hex.Length/2)
        for($i=0;$i -lt $tx.Length;$i++) { $tx[$i]=[Convert]::ToByte($item.tx_hex.Substring(2*$i,2),16) }
        $watch=[System.Diagnostics.Stopwatch]::StartNew()
        $raw=[System.Collections.Generic.List[byte]]::new()
        $problem=$null
        try {
            if ($item.split_at -gt 0) {
                $serial.Write($tx,0,$item.split_at)
                Start-Sleep -Milliseconds $item.gap_ms
                $serial.Write($tx,$item.split_at,$tx.Length-$item.split_at)
            } else { $serial.Write($tx,0,$tx.Length) }
            $header=Read-Bytes 12
            $raw.AddRange($header)
            if ([System.Text.Encoding]::ASCII.GetString($header,0,4) -cne 'RVEC') { throw 'Unexpected response magic.' }
            $length=[BitConverter]::ToUInt16($header,8)
            if ($length -gt 520) { throw "Unexpected response size $length." }
            $raw.AddRange((Read-Bytes ($length+4)))
        } catch { $problem=$_.Exception.Message }
        $watch.Stop()
        $row=[ordered]@{
            name=$item.name; rx_hex=([BitConverter]::ToString($raw.ToArray()).Replace('-','').ToLowerInvariant())
            host_ms=$watch.Elapsed.TotalMilliseconds; transport_error=$problem
        }
        $writer.WriteLine(($row | ConvertTo-Json -Compress))
        $writer.Flush()
        if ($problem) { throw "$($item.name): $problem" }
        $finished++
        if (($finished % 10) -eq 0) { Write-Output "Transport: $finished / $($items.Count) responses received." }
    }
    $serial.ReadTimeout=150
    try {
        $extra=$serial.ReadByte()
        throw "Unexpected trailing byte $extra."
    } catch [System.TimeoutException] { }
} catch { $failure=$_.Exception.Message }
finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
    $writer.Dispose()
    [ordered]@{
        timestamp=(Get-Date -Format o); port=$Port; baud=115200
        responses=$finished; expected=$items.Count; error=$failure
        status=$(if($failure){'FAIL'}else{'PASS'})
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDirectory 'transport.json') -Encoding UTF8
}
if($failure) { throw $failure }
Write-Output 'PASS: physical serial transactions captured; Python arithmetic verification follows.'
