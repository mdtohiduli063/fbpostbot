# Background music for news videos

The bot turns every news image into a short 15–20 second video.
It picks **one random track** from this folder for each video.

## How to add tracks

1. Drop your music files directly into this folder (`audio/`).
2. Recommended file names: `NEWSAUDIO1.mp3`, `NEWSAUDIO2.mp3`, etc.
3. Supported formats: `.mp3`, `.m4a`, `.wav`, `.aac`, `.ogg`, `.flac`.
4. Each track should ideally be **at least 25 seconds long** so it covers
   the whole video with smooth fade-in / fade-out.

## What if this folder is empty?

The bot still runs — it will simply render a **silent** video
(image + Ken-Burns zoom, no music). As soon as you add any audio
file here, the next post will use it.

## Tips

- Royalty-free / copyright-safe tracks only — Facebook may mute videos
  that infringe music copyright.
- Mellow, dramatic, or news-cinematic tracks work best.
- You can change the volume / fade by editing the `news_video` section
  in `config.json`.
