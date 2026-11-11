# 📱 ENI Premium Store — Full Stack (Telegram Bot + FastAPI + Flutter Android App + GitHub Actions)

ဤ Zip ဖိုင်ထဲတွင် သင်၏ မူရင်း Telegram Bot နှင့်အတူ Android Mobile App အတွက် လိုအပ်သော Backend နှင့် Frontend ကုဒ်အပြည့်အစုံ ပါဝင်ပါသည်-

## 📂 Folder ဖွဲ့စည်းပုံ
1. **`backend/my_shop_bot/`**
   - သင်၏ မူရင်း Telegram Bot ဖိုင်များ (`main.py`, `database.py`, `outline_api.py`, `crypto_api.py`, `handlers/`)
   - **`api.py`** — Mobile App နှင့် ချိတ်ဆက်ပေးမည့် FastAPI REST Server
   - **`run_all.py`** — Telegram Bot နှင့် FastAPI Server နှစ်ခုလုံးကို Command တစ်ကြောင်းတည်းဖြင့် ပြိုင်တူ Run ပေးမည့်ဖိုင်
2. **`mobile_app/`**
   - Flutter Android App Source Code အပြည့်အစုံ (`lib/main.dart`, `lib/api_service.dart`, `lib/screens/`)
3. **`.github/workflows/build_android_apk.yml`**
   - သင့်ကွန်ပျူတာတွင် Flutter သွင်းစရာမလိုဘဲ **GitHub Actions** ပေါ်တွင် Cloud မှတစ်ဆင့် `.apk` ဖိုင်ကို အလိုအလျောက် ထုတ်ပေးမည့် Workflow ဖိုင်။

---

## 🚀 အဆင့် ၁ - VPS Server ပေါ်တွင် Backend (Bot + API) Run နည်း
```bash
cd backend/my_shop_bot
pip install -r requirements.txt
python3 run_all.py
```
- `run_all.py` သည် Telegram Bot ကိုလည်း Run ပေးသလို Port `8000` တွင် Mobile App API (`http://YOUR_SERVER_IP:8000/api`) ကိုပါ တစ်ပြိုင်နက် ဖွင့်ပေးပါသည်။

---

## ☁️ အဆင့် ၂ - Flutter မသွင်းဘဲ GitHub Actions ဖြင့် APK ထုတ်ယူနည်း
1. GitHub တွင် **Private Repository** အသစ်တစ်ခု ဆောက်ပါ။
2. ဤ Zip ဖိုင်ဖြည်ထားသော Folder တစ်ခုလုံး (`backend`, `mobile_app`, `.github`) ကို ထို Repository ထဲသို့ Upload / Push တင်ပါ။
3. GitHub Repository ၏ **Actions** tab သို့ ဝင်ပါ။
4. **"Build ENI Store Android APK"** workflow ကိုနှိပ်ပြီး **Run workflow** တွင် သင်၏ Server URL (ဥပမာ `http://YOUR_VPS_IP:8000/api`) ထည့်၍ Run လိုက်ပါ။
5. ၃ မိနစ်ခန့်အကြာ Build ပြီးသွားသောအခါ အောက်ဆုံးရှိ **Artifacts** ကဏ္ဍတွင် **`ENI-Premium-Store-Release-APK`** ကို နှိပ်၍ `app-release.apk` ကို တိုက်ရိုက် Download ဆွဲယူနိုင်ပါပြီ။
