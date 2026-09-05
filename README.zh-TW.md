# Panda Jetpack

控制 **BIQU Panda Jetpack V2** 的 RGB 燈 —— 那是 Bambu Lab P1／X1 列印頭上的
導風罩。一支零依賴的 CLI，加一個 Home Assistant integration。

[English](README.md)

## ⚠️ 安全性

`ws://<ip>/ws` **沒有任何驗證**，而且一連上就主動送出完整狀態 —— 裡面有明文的
**WiFi 密碼**、裝置 **AP 密碼**、以及印表機的 **access code**。同網段任何裝置
一秒內就能讀走。

這是韌體問題，從外面修不了。CLI 與 integration 都在讀進來的第一時間就把這三個
欄位砍掉，所以它們不會進到終端機、log、entity 屬性或診斷檔。**請維持這個行為。**

緩解方式：把 Jetpack 和印表機放到隔離的 VLAN 或獨立 SSID，只開主網段進入的
單向防火牆規則。這樣它存的就只是那個隔離網路的密碼，而 Home Assistant 照樣
連得到。

## CLI

零依賴，用系統內建的 Python 就能跑。

```
./jetpack.py status                # 目前狀態（密碼已遮蔽）
./jetpack.py status --json
./jetpack.py mode breathing        # 切燈效（名稱或編號都可以）
./jetpack.py color static red      # 某個燈效的顏色
./jetpack.py brightness h2d 80     # 0-100
./jetpack.py speed breathing 30    # 0-100
./jetpack.py on static --off       # 關燈
./jetpack.py follow                # 燈跟隨印表機狀態
./jetpack.py warning --off         # 高溫警告不要蓋過目前燈效
./jetpack.py safe strobing         # 安全溫度區間的樣式
./jetpack.py danger static
./jetpack.py h2d printing green    # h2d 各狀態的顏色（網頁做不到）
./jetpack.py rgb-reset
./jetpack.py restart
./jetpack.py palette blue --id 3   # 網頁色票，不會改變燈
```

主機預設 `192.168.31.142`，用 `--host` 或 `$JETPACK_HOST` 覆蓋。

## Home Assistant

把 `custom_components/panda_jetpack/` 複製到 `config/custom_components/`，
重啟後在「設定 → 裝置與服務」新增 **Panda Jetpack**。

| Entity | 對應功能 |
|---|---|
| `light` | 開關、亮度、RGB、effect（10 種模式） |
| `switch` × 2 | 跟隨印表機、高溫警告覆蓋 |
| `select` × 2 | 安全／危險溫度樣式 |
| `number` | 燈效速度 |
| `button` × 2 | 重設燈光設定、重新開機 |
| service `set_h2d_color` | h2d 各狀態的顏色 |

h2d 的三個顏色以唯讀屬性呈現（`h2d_idle_color`、`h2d_printing_color`、
`h2d_error_color`），用 service 修改 —— 它們是一種 effect 的參數，不是三顆燈。

## 協定

只開 80 埠，除了 `/` 以外所有路徑都導到 captive portal。控制走 WebSocket
`ws://<ip>/ws`，形狀一律是 `{"<root>": {<欄位>: <值>}}`。唯一的 POST 是韌體 OTA。

兩個要注意的地方：裝置**一連上就主動吐完整狀態**，而且**對任何訊息都不回覆**。
「送出後沒回應」不能當作失敗的證據 —— 唯一可信的確認方式是斷線、重連、讀狀態。

| Root | 訊息 |
|---|---|
| `settings` | `rgb_info_mode`、`rgb_rgba`（可加 `rgb_state_index`）、`rgb_info_brightness`、`rgb_info_speed`、`on`、`follow`、`warning_override`、`safe_effect`、`danger_effect`、`rgb_reset`、`reset`、`factory_reset`、`language` |
| `block` | `blockID` + `blockrgba` —— 色票，**不是 LED** |
| `wifi` | `ssid`+`password`、`scan` |
| `ap` | `ssid`+`password`+`ip`、`on` |
| `sta` | `hostname` |
| `printer` | `name`+`sn`+`access_code`+`ip`、`scan`、`disconnect` |

### 燈效模式

送出的值是網頁 `g_rgb_type_str` 陣列的索引，**不是** UI 翻譯字串 `rgb_info_modeN`
的那個 N —— 兩者在 7 之後分岔。高溫警告是 **7**，不是 8。

`0` static · `1` breathing · `2` strobing · `3` wave · `4` marquee · `5` cycle ·
`6` rainbow · `7` warning · `8` fan · `9` h2d

顏色格式 `#RRGGBBAA`。

### h2d 三色

`h2d`（模式 9）有三個顏色，對應印表機的 idle／printing／error 三個狀態，靠
`rgb_rgba` 旁邊的 `rgb_state_index` 0／1／2 指定。

帶 index 會**同時**寫入 `list3[0].h2d_rgba[i]` 與 `list2[9].rgb_rgba`；不帶
就只寫 `list2[9]`。韌體不檢查範圍 —— 送 3 會寫到位置 2。

## V1.0.0 韌體的 bug

網頁 UI **完全沒辦法設定 h2d 三色**，起因是三個各自獨立的 bug：

1. 它在附加 `rgb_state_index` 前檢查的是 `colorButton_id==8`，但 h2d 是 `9` ——
   所以選 h2d 永遠走到省略 index 的那個分支。
2. `querySelector('.idle.color-item')` 永遠找不到東西；按鈕建立時用的 class 是
   `Idle`／`Printing`／`Printer-Error`。
3. h2d 面板那七個按鈕綁的是 `show_note_h2d_printer`（顯示說明），不是色盤，
   所以 `state_color_list[9]` 從來沒被設定過。

協定本身沒問題。`./jetpack.py h2d` 與 `set_h2d_color` service 就是補上 UI 漏掉
的那個 index。

## 已知限制

- **亮度與速度讀不回來。** 裝置回報的 `list2` 是存起來的預設值，不是生效值 ——
  燈確實會變暗，但那些數字不會動。兩邊工具都自己記著送出的值；HA 重啟後顯示的
  數字會退回 `list2`，可能與眼睛看到的不符。
- **顏色、亮度、速度都是每個燈效各自一份**，不是全域。操作套用在當下選中的燈效。
- 裝置不推送狀態，integration 每 30 秒重讀一次。
- `follow` 的旗標驗證過了，但實際燈效要有列印工作在跑才看得到。
- `restart` 訊息送得出去，但裝置約 2 秒就回應，所以「真的重開了」未經確認。

## 已證實不成立

- `blockID` 0–19 **不是** LED，是網頁取色頁下半部那排 20 格色票。改它不會讓
  任何燈變色。
- `ws_theme`（把 15 個列印階段的 GIF 上色）在 V1.0.0 **沒有實作**：整份 UI 沒有
  `theme` root、`theme_item_recolor_create` 被呼叫 0 次、`id_card_theme_gif` 不在
  靜態 HTML 裡，兩種訊息形狀送出後狀態的頂層 key 都沒變。

## 沒有實作

`factory_reset`（會清掉 WiFi 設定，太容易變磚）、`wifi scan`、
`printer scan/bind`，以及 `POST /ota` 的 GIF 上傳（會寫進 flash）。

## 授權

MIT
