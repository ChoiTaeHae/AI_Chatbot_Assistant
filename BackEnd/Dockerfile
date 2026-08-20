FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# 시스템 패키지
RUN apt-get update && apt-get install -y \
    python3.11 python3.11-dev python3-pip \
    build-essential curl git cmake ninja-build \
    libglib2.0-0 libsm6 libxrender1 libxext6 \
    libspatialindex-dev \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
RUN update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

WORKDIR /app

# torch CUDA 먼저 설치 (requirements 의존성 해결 시 재다운로드 방지)
RUN pip install --no-cache-dir \
    torch==2.7.0 torchvision==0.22.0 \
    --index-url https://download.pytorch.org/whl/cu128

# 나머지 패키지 설치 (pywin32, llama-cpp-python, torch 제외)
COPY requirements_lock.txt .
RUN grep -v -E "pywin32|llama-cpp-python|^torch|^torchvision" requirements_lock.txt > requirements_docker.txt && \
    pip install --no-cache-dir --no-deps -r requirements_docker.txt

# CUDA 링커 경로 등록 (빌드 시점에 stub 라이브러리 인식)
RUN echo "/usr/local/cuda/lib64" >> /etc/ld.so.conf.d/cuda.conf && \
    echo "/usr/local/cuda/lib64/stubs" >> /etc/ld.so.conf.d/cuda-stubs.conf && \
    ldconfig

# llama-cpp-python CUDA 소스 빌드 (RTX 3070 = compute capability 8.6)
RUN CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=86" \
    FORCE_CMAKE=1 \
    pip install --no-cache-dir llama-cpp-python==0.3.29

# ── 아래 pip 설치는 반드시 llama-cpp CUDA 컴파일 '뒤'에 둔다 ──────────────────
# Docker 레이어 캐시는 순차적이라, 한 줄이라도 앞에서 바뀌면 그 뒤가 전부 다시 돈다.
# 예전엔 이 줄들이 위에 있어서 SDK를 하나 추가할 때마다 20~40분짜리 llama-cpp
# 재컴파일이 딸려왔다(실측: google-genai를 추가한 커밋이 그랬고, 그 탓에 리빌드를
# 미루다 이미지에 google-genai가 없는 채로 vertex 모드가 ImportError로 죽었다).
# 여기 두면 컴파일까지 캐시가 살아남아 SDK 추가가 pip 설치 몇 초로 끝난다.
#
# 버전은 고정한다. requirements_lock.txt와 달리 여기서만 설치되는 패키지라
# 고정하지 않으면 리빌드 시점의 최신 버전이 들어와, 지금 검증한 것과 다른 환경이 만들어진다
# (특히 google-genai가 바뀌면 Gemini 호출부가 조용히 깨질 수 있다).
# 값은 2026-08-13 기준 실동작 확인된 버전이다.

# llama-cpp-python 의존성 — 위 llama-cpp 설치가 끌어온 버전을 검증된 버전으로 되돌린다
RUN pip install --no-cache-dir diskcache==5.6.3

# Vertex AI (Gemini) SDK — LLM_PROVIDER=vertex 일 때 답변 생성에 사용 (의존성 포함 설치)
RUN pip install --no-cache-dir google-genai==2.12.1

# Cloud Translation API SDK — 답변 후처리 번역(다국어 지원)에 사용. Vertex와 같은 GCP 인증 재사용.
RUN pip install --no-cache-dir google-cloud-translate==3.27.0

# 앱 코드 복사
COPY . .

EXPOSE 8000

CMD ["python3", "-m", "uvicorn", "app.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
