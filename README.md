# KDX

第一個夢想小程式實作！

一直很想實作看看一些好玩的小程式讓自己的生活更加方便。平常在學校雖然學習很多資訊、程式、人工智慧、語言模型技術，但對我來說好像都在紙上談兵，解決了很難的研究問題但觸碰不到日常生活。平時累積了一些想法剛好在這個暑假有多一點時間做一些自己喜歡的事，決定選這個當作我的第一個簡單程式專案！雖然對於投資高手這個程式應該對他們沒什麼幫助，但我想它也會隨著我的投資策略變化跟著我一起強大！

## 主要解決問題

類似到價通知的想法，以 KD 技術指標為基礎，利用指標走勢找到進出場時機。

## 整體流程

1. 在 LINE 對 bot 說：`add 2330 0050`
2. `line_webhook.py` 收到訊息 → 解析指令 → 更新 `subscriptions.json`
3. 每天 13:40（台北）`launchd` 叫 `run_kd.sh` 起床
4. `run_kd.sh` 載入 `.env`、呼叫 `kd_strategyB.py`
5. `kd_strategyB.py` 下載行情 → 算 KD/均線 → 判斷 Entry/Reduce/Exit
6. 若觸發 → `line_push.py` 用 Messaging API 推播

## 設計互動介面

1. 中文/英文
    1. 中文：
        
        
    2. 

## 檔案設定

- `line_push.push_text()` → LINE 推播
- `subscriptions.all_symbols_to_subscribers()` → 讀取追蹤清單
- `config_loader.load_config()` → 設定
- `institutions.get_institutions()` → 三大法人買賣資料
