# Generates synthetic call recordings (WAV) with Windows built-in TTS so the
# AI_TRANSCRIBE path can be demonstrated end-to-end. No real customer audio is used.
# Usage: powershell -File scripts/generate_audio.ps1
Add-Type -AssemblyName System.Speech
$out = Join-Path $PSScriptRoot "..\data\audio"
New-Item -ItemType Directory -Force -Path $out | Out-Null

$calls = @{
  "C10238_IC10238-6.wav" = @(
    "Thank you for calling. How can I help you today?",
    "Hi, this is about my fee reversal again. It is still not done after six weeks.",
    "I am sorry sir. I can see it is still pending with operations.",
    "My fixed rate ends on the twenty third of October and another bank has offered me a better rate. If nobody senior calls me this week I will move my home loan."
  );
  "C10417_IC10417-4.wav" = @(
    "Hello, this is a courtesy call about your overdue instalment.",
    "I understand. I lost my job in August. I have an offer letter for next month but I need a few weeks.",
    "We can review a hardship plan for you.",
    "Thank you, that would really help. Please stop the late fees until then."
  )
}
foreach ($name in $calls.Keys) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $voices = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }
  $s.SetOutputToWaveFile((Join-Path $out $name))
  $i = 0
  foreach ($line in $calls[$name]) {
    if ($voices.Count -gt 1) { $s.SelectVoice($voices[$i % $voices.Count]) }
    $s.Speak($line); $i++
  }
  $s.Dispose()
  Write-Output "generated $name"
}
