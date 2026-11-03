"""Window with the camera's live video."""

import tkinter as tk
from pidreams.ui import theme


class CameraWindowMixin:
    """Window with the camera's live video."""

    # ── Camera window ────────────────────────────────────────────────────────
    # Shows live the same video ver_camera takes its photo from. Closing the
    # window turns the camera off, as in any app.

    _CAM_W, _CAM_H = 480, 360

    def _open_camera_window(self):
        if getattr(self, "_cam_win", None) is not None:
            self._cam_win.lift()
            return
        from pidreams.camera.stream import STREAM

        win = tk.Toplevel(self.root, bg=theme.GLASS)
        win.title("PI dreams — Câmera")
        win.geometry(f"{self._CAM_W + 16}x{self._CAM_H + 44}")
        win.minsize(240, 200)
        win.protocol("WM_DELETE_WINDOW", self._toggle_camera)   # closing it turns the camera off

        self._cam_view = tk.Label(win, bg=theme.BG, text="iniciando a câmera…",
                                  fg=theme.MUTED, font=theme.FONT_SMALL,
                                  highlightthickness=3, highlightbackground=theme.BORDER)
        self._cam_view.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))
        self._cam_caption = tk.Label(win, text="● Ao vivo: o que o PI dreams vê",
                                     bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL)
        self._cam_caption.pack(pady=(0, 6))

        self._cam_win = win
        self._cam_img = None          # live PhotoImage reference (otherwise Tk drops it)
        STREAM.on_snapshot(lambda: self.root.after(0, self._blink_camera))
        self._tick_camera()

    def _close_camera_window(self):
        win = getattr(self, "_cam_win", None)
        self._cam_win = None
        if win is not None:
            win.destroy()

    def _tick_camera(self):
        if self._cam_win is None:
            return
        try:
            import cv2
            from PIL import Image, ImageTk
            from pidreams.camera.stream import STREAM

            frame = STREAM.latest()
            if frame is None:
                self._cam_view.config(image="", text="sem imagem da câmera")
            else:
                # Mirrored only on screen, like every video app; the model gets
                # the original image (readable text).
                frame = cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
                box_w = max(self._cam_view.winfo_width() - 6, 1)
                box_h = max(self._cam_view.winfo_height() - 6, 1)
                h, w = frame.shape[:2]
                scale = min(box_w / w, box_h / h)
                if scale > 0 and (box_w > 10 and box_h > 10):
                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)),
                                       interpolation=cv2.INTER_AREA)
                self._cam_img = ImageTk.PhotoImage(Image.fromarray(frame))
                self._cam_view.config(image=self._cam_img, text="")
        except Exception as e:
            self._cam_view.config(image="", text=f"erro na prévia: {e}")
        self.root.after(40, self._tick_camera)       # ~25 fps

    def _blink_camera(self):
        """The model just took the photo: the border lights up for a moment."""
        if self._cam_win is None:
            return
        self._cam_view.config(highlightbackground=theme.TEXT)
        self._cam_caption.config(text="● Foto enviada ao modelo", fg=theme.TEXT)

        def _back():
            if self._cam_win is not None:
                self._cam_view.config(highlightbackground=theme.BORDER)
                self._cam_caption.config(text="● Ao vivo: o que o PI dreams vê",
                                         fg=theme.MUTED)
        self.root.after(1500, _back)
