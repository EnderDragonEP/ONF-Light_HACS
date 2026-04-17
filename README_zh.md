# ONF Light — Home Assistant 整合

[English](README.md) | [中文](README_zh.md)

![logo](custom_components\onf_light\brand\dark_logo.png)

這是用於控制 ONF 藍牙植物燈的 Home Assistant 整合（由官方 Android 應用反向工程得來）。提供對受支援 ONF 型號的亮度與色溫（CCT）控制，透過藍牙低功耗（Nordic UART）協定直接與裝置通訊。

本專案應用了官方 ONF 應用中觀察到的相同協定與裝置特定行為，包含：依型號調整的 CCT 範圍、防彈跳與樂觀更新、以及混合式 BLE 連線策略以提升控制穩定性。

**支援：** ONF BLE 燈（多種型號 — 僅亮度與可調白光型）。僅在 MIST O+ 上有測試。

**警告：** 此整合直接與藍牙裝置通訊；需要 Home Assistant 主機具有可用的藍牙介面與作業系統層級的藍牙權限。

---

## 功能

- 亮度控制
- 色溫（CCT）控制，以克耳文（Kelvin）為單位輸出屬性
- 型號辨識（會正確處理僅支援亮度的型號）
- 樂觀更新、消抖與回讀確認以減少 UI 抖動
- 混合式 BLE 連線（具閒置時間限制的長連線）與逐指令重試機制
- 若可用，會自動透過 Home Assistant 的藍牙進行發現

## 要求

- 支援藍牙的 Home Assistant（Linux 使用 bluez、macOS 或支援的藍牙介面）
- Python 3.10+（與 Home Assistant core 相容）

## 安裝

手動安裝（HACS 或 custom components）：

1. 將 `custom_components/onf_light` 資料夾複製到 Home Assistant 的 `config` 目錄下的 `custom_components`。
2. 重新啟動 Home Assistant。
3. 透過整合（Integrations）介面設定或新增設定項目。

## 使用 HACS 安裝

若使用 HACS：

1. 在 Home Assistant 的 HACS → 右上三點選單 → Custom repositories。
2. 新增此 repository 的 URL，分類選 `integration`。
3. 在 HACS 中搜尋 "ONF Light" 並點選安裝。
4. 安裝後重新啟動 Home Assistant。
5. 前往 Settings → Integrations，若附近有 ONF 裝置應會看到設定通知，依提示完成設定。

## 使用說明

- 亮度：採用 Home Assistant 標準的亮度（0-255）。
- 色溫：以 `color_temp_kelvin` 屬性（克耳文）。整合會依裝置的內部步進轉換克耳文值，並為需量化的型號做取整處理。

注意：

- 某些 ONF 型號僅支援亮度；整合會只顯示該等裝置支援的控制項。
- 發送變更後，整合會短時間回讀裝置以確認狀態，避免顯示過時狀態造成介面跳動。

## 疑難排解

- 裝置變為不可用：請確認 Home Assistant 主機的藍牙介面已啟用且在範圍內。如有需要，重新載入整合。
- 更改未生效：檢查 Home Assistant 日誌是否有 BLE 通訊錯誤，並確認裝置已開機且未被其他應用連線。

## 致謝

- 反向工程與實作參考自使用 JADX 反編譯的 ONF 官方 Android 應用資源。
- 使用了 Claude 4.6，GPT-5.3-Codex 進行 AI 加速開發。
