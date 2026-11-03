"""ver_camera tool exposed to the agent — exists only while the Camera service is on."""

from pidreams.agent.tools import register_service_tools

SERVICE = "camera"

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "ver_camera",
            "description": (
                "Seus olhos: tira uma foto AGORA pela webcam do usuário e responde uma "
                "pergunta sobre ela. Use SEMPRE que a resposta depender do que a "
                "câmera mostra — inclusive quando vier como pergunta, não como ordem: "
                "'tá me vendo?', 'você consegue me ver?', 'como eu estou?', "
                "'o que eu tô segurando?', 'que cor é minha camisa?', 'quantos dedos "
                "eu tô mostrando?', 'lê esse papel', 'olha isso aqui'. Nunca responda "
                "sobre a aparência do usuário, o que ele segura, mostra ou veste, ou o "
                "ambiente dele sem chamar esta ferramenta: você não enxerga nada sem ela."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pergunta": {
                        "type": "string",
                        "description": (
                            "O que o usuário quer saber sobre a imagem, em português "
                            "(ex.: 'o que a pessoa está segurando na mão?')."
                        ),
                    }
                },
                "required": ["pergunta"],
            },
        },
    },
]


def _look_camera(pergunta: str) -> str:
    # Late import: cv2 only loads when the camera is actually used.
    from pidreams.camera.vision import look_camera

    return look_camera(pergunta)


HANDLERS = {"ver_camera": _look_camera}


def register() -> None:
    """Idempotent — may be called every time the service is turned on."""
    register_service_tools(SERVICE, TOOL_SCHEMAS, HANDLERS)
