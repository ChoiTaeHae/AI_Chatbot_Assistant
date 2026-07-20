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

# llama-cpp-python 의존성
RUN pip install --no-cache-dir diskcache

# Vertex AI (Gemini) SDK — LLM_PROVIDER=vertex 일 때 답변 생성에 사용 (의존성 포함 설치)
RUN pip install --no-cache-dir google-genai

# CUDA 링커 경로 등록 (빌드 시점에 stub 라이브러리 인식)
RUN echo "/usr/local/cuda/lib64" >> /etc/ld.so.conf.d/cuda.conf && \
    echo "/usr/local/cuda/lib64/stubs" >> /etc/ld.so.conf.d/cuda-stubs.conf && \
    ldconfig

# llama-cpp-python CUDA 소스 빌드 (RTX 3070 = compute capability 8.6)
RUN CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=86" \
    FORCE_CMAKE=1 \
    pip install --no-cache-dir llama-cpp-python==0.3.29

# 앱 코드 복사
COPY . .

EXPOSE 8000

CMD ["python3", "-m", "uvicorn", "app.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
