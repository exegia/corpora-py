from fastapi.routing import APIRoute


def generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"
