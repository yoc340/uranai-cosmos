# 猫キャラ画像 一括リネームスクリプト
# 実行場所: C:\Users\yoc34\OneDrive\デスクトップ\uranai-cosmos\static\cats

$folder = "C:\Users\yoc34\OneDrive\デスクトップ\uranai-cosmos\static\cats"

$renameMap = @{
    "8C547F3D-0E49-4EE0-B67D-EB3F58E28532.png" = "cat_aries.png"        # おひつじ座
    "8DA56380-8446-4D41-8371-0AA59DB99380.png" = "cat_taurus.png"       # おうし座
    "0765076F-145C-4B4E-9B50-287200786144.png" = "cat_gemini.png"       # ふたご座
    "9702C19E-DE4A-4E93-BC36-1FF9CEA9C9BF.png" = "cat_cancer.png"      # かに座
    "A20BD555-D975-415E-9BC2-BD83EE6B89A9.png" = "cat_leo.png"         # しし座
    "F2C959E0-F56D-4BAC-99A7-4D6A85451317.png" = "cat_virgo.png"       # おとめ座
    "95E18061-990C-47C6-A6CE-B10511A839B2.png" = "cat_libra.png"       # てんびん座
    "3201E506-FD03-4872-ADC6-955FFA3F40F4.png" = "cat_scorpio.png"     # さそり座
    "DBDE91DE-A4A2-49C6-9FCA-1AA43ACCC6AF.png" = "cat_sagittarius.png" # いて座
    "1C3D89EA-A901-4312-8820-7B803EEC8F4D.png" = "cat_capricorn.png"   # やぎ座
    "A6DBC81A-858C-42E9-8C3A-C63D2C52C70D.png" = "cat_aquarius.png"   # みずがめ座
    "4224AD66-C680-4150-BCCB-337E2CF77BE9.png" = "cat_pisces.png"      # うお座
}

foreach ($old in $renameMap.Keys) {
    $oldPath = Join-Path $folder $old
    $newPath = Join-Path $folder $renameMap[$old]
    if (Test-Path $oldPath) {
        Rename-Item -Path $oldPath -NewName $renameMap[$old]
        Write-Host "✅ $old → $($renameMap[$old])"
    } else {
        Write-Host "⚠️  見つかりません: $old"
    }
}

Write-Host ""
Write-Host "完了！ファイル一覧:"
Get-ChildItem $folder | Select-Object Name
