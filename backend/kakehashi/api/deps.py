from typing import Annotated

from fastapi import Depends, Request

from kakehashi.context import AppContext


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]
