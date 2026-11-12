"""설정 진입점.

Render 는 배포 환경에 RENDER 환경변수를 자동으로 넣어준다.
- RENDER 있음 → 운영(prod)
- 그 외(로컬 개발/테스트) → 개발(dev)
"""

import os

if os.getenv("RENDER"):
    from .prod import *  # noqa: F401,F403
else:
    from .dev import *  # noqa: F401,F403
