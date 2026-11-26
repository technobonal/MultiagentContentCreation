# Modelos locales

## `face_detection_yunet_2023mar.onnx`

Detector de caras YuNet. Lo usa `app/fuentes/detectar_caras.py` para que los recortes de fotos no corten cabezas. Corre en la máquina: no envía imágenes a nadie.

- Origen: repositorio oficial `opencv/opencv_zoo`, carpeta `models/face_detection_yunet` (descargado el 2026-11-26 con el permiso de Frank).
- Licencia: MIT (`LICENSE-yunet`).
- Tamaño: 232589 bytes. SHA-256: `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` (un test lo comprueba).
