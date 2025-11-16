# BmCodex Premium Userbot
Userbot Telegram berbasis **Telethon** dengan fitur lengkap premium:

- 🚀 **Premium Invite Engine** (super cepat & aman)
- 🔥 **Auto Flood Detection** + auto sleep
- 🛡 **Anti-ban & anti-flood wait**
- ⚡ **Adaptive Speed** (warm mode → fast mode)
- ♻️ **Rotating Queue + per-user cooldown**
- 📌 **Resume progress lewat database.json**
- 🔄 **Heroku Deploy Ready**
- 🧩 Modular & mudah diperluas

## Deploy ke Heroku
[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://www.heroku.com/deploy?template=https://github.com/bimazainudinikhsan/BmCodex)

## Environment Variables
| Nama | Wajib | Deskripsi |
|------|:-----:|-----------|
| API_ID | ✔️ | API ID Telegram |
| API_HASH | ✔️ | API Hash Telegram |
| SESSION_STRING | ✔️ | StringSession akun Telegram |

## Commands
```
.status
.premiuminvite @target
.start
```

## Struktur Folder
```
BmCodex/
│── main.py
│── app.json
│── Procfile
│── README.md
│── requirements.txt
│── database.json
└── modules/
    └── premium_invite_engine.py
```


### New Commands:
```
.inviteall @target
.invitemember 10 @target
```