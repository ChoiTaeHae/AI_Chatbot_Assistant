---
base_model:
- meta-llama/Meta-Llama-3-8B
language:
- en
- ko
library_name: transformers
license: llama3
---

<a href="https://github.com/MLP-Lab/Bllossom">
  <img src="https://cdn-uploads.huggingface.co/production/uploads/64a90711c05da19ca834f690/a0VE5UCY1HCEhaHtp3mGa.png" alt="image" width="30%" height="30%">
</a>



# Update!
* ~~[2024.08.09] Llama3.1 버전을 기반으로한 Bllossom-8B로 모델을 업데이트 했습니다. 기존 llama3기반 Bllossom 보다 평균 5%정도 성능 향상이 있었습니다.~~(수정중에 있습니다.)
* [2024.06.18] 사전학습량을 **250GB**까지 늘린 Bllossom ELO모델로 업데이트 되었습니다. 다만 단어확장은 하지 않았습니다. 기존 단어확장된 long-context 모델을 활용하고 싶으신분은 개인연락주세요!
* [2024.06.18] Bllossom ELO 모델은 자체 개발한 ELO사전학습 기반으로 새로운 학습된 모델입니다. [LogicKor](https://github.com/StableFluffy/LogicKor) 벤치마크 결과 현존하는 한국어 10B이하 모델중 SOTA점수를 받았습니다. 

LogicKor 성능표 :
| Model | Math | Reasoning | Writing | Coding | Understanding | Grammar | Single ALL | Multi ALL | Overall |
|:---------:|:-----:|:------:|:-----:|:-----:|:----:|:-----:|:-----:|:-----:|:----:|
| gpt-3.5-turbo-0125 | 7.14 | 7.71 | 8.28 | 5.85 | 9.71 | 6.28 | 7.50 | 7.95 | 7.72 |
| gemini-1.5-pro-preview-0215 | 8.00 | 7.85 | 8.14 | 7.71 | 8.42 | 7.28 | 7.90 | 6.26 | 7.08 |
| llama-3-Korean-Bllossom-8B | 5.43 | 8.29 | 9.0 | 4.43 | 7.57 | 6.86 | 6.93 | 6.93 | 6.93 |



# Bllossom | [Demo]() | [Homepage](https://www.bllossom.ai/) | [Github](https://github.com/MLP-Lab/Bllossom) |

<!-- [GPU용 Colab 코드예제](https://colab.research.google.com/drive/1fBOzUVZ6NRKk_ugeoTbAOokWKqSN47IG?usp=sharing) | -->
<!-- [CPU용 Colab 양자화모델 코드예제](https://colab.research.google.com/drive/129ZNVg5R2NPghUEFHKF0BRdxsZxinQcJ?usp=drive_link) -->

```bash
저희 Bllossom팀 에서 한국어-영어 이중 언어모델인 Bllossom을 공개했습니다!
서울과기대 슈퍼컴퓨팅 센터의 지원으로 100GB가넘는 한국어로 모델전체를 풀튜닝한 한국어 강화 이중언어 모델입니다!
한국어 잘하는 모델 찾고 있지 않으셨나요?
 - 한국어 최초! 무려 3만개가 넘는 한국어 어휘확장
 - Llama3대비 대략 25% 더 긴 길이의 한국어 Context 처리가능
 - 한국어-영어 Pararell Corpus를 활용한 한국어-영어 지식연결 (사전학습)
 - 한국어 문화, 언어를 고려해 언어학자가 제작한 데이터를 활용한 미세조정
 - 강화학습
이 모든게 한꺼번에 적용되고 상업적 이용이 가능한 Bllossom을 이용해 여러분 만의 모델을 만들어보세욥!
무려 Colab 무료 GPU로 학습이 가능합니다. 혹은 양자화 모델로 CPU에올려보세요 [양자화모델](https://huggingface.co/MLP-KTLim/llama-3-Korean-Bllossom-8B-4bit)

1. Bllossom-8B는 서울과기대, 테디썸, 연세대 언어자원 연구실의 언어학자와 협업해 만든 실용주의기반 언어모델입니다! 앞으로 지속적인 업데이트를 통해 관리하겠습니다 많이 활용해주세요 🙂
2. 초 강력한 Advanced-Bllossom 8B, 70B모델, 시각-언어모델을 보유하고 있습니다! (궁금하신분은 개별 연락주세요!!)
3. Bllossom은 NAACL2024, LREC-COLING2024 (구두) 발표로 채택되었습니다.
4. 좋은 언어모델 계속 업데이트 하겠습니다!! 한국어 강화를위해 공동 연구하실분(특히논문) 언제든 환영합니다!! 
   특히 소량의 GPU라도 대여 가능한팀은 언제든 연락주세요! 만들고 싶은거 도와드려요.
```

The Bllossom language model is a Korean-English bilingual language model based on the open-source LLama3. It enhances the connection of knowledge between Korean and English. It has the following features:

* **Knowledge Linking**: Linking Korean and English knowledge through additional training
* **Vocabulary Expansion**: Expansion of Korean vocabulary to enhance Korean expressiveness.
* **Instruction Tuning**: Tuning using custom-made instruction following data specialized for Korean language and Korean culture
* **Human Feedback**: DPO has been applied
* **Vision-Language Alignment**: Aligning the vision transformer with this language model 

**This model developed by [MLPLab at Seoultech](http://mlp.seoultech.ac.kr), [Teddysum](http://teddysum.ai/) and [Yonsei Univ](https://sites.google.com/view/hansaemkim/hansaem-kim)**

## Demo Video

<div style="display: flex; justify-content: space-between;">
  <!-- 첫 번째 컬럼 -->
  <div style="width: 49%;">
    <a>
      <img src="https://github.com/lhsstn/lhsstn/blob/main/x-llava_dem.gif?raw=true" style="width: 100%; height: auto;">
    </a>
    <p style="text-align: center;">Bllossom-V Demo</p>
  </div>

  <!-- 두 번째 컬럼 (필요하다면) -->
  <div style="width: 49%;">
    <a>
      <img src="https://github.com/lhsstn/lhsstn/blob/main/bllossom_demo_kakao.gif?raw=true" style="width: 70%; height: auto;">
    </a>
    <p style="text-align: center;">Bllossom Demo(Kakao)ㅤㅤㅤㅤㅤㅤㅤㅤ</p>
  </div>
</div>



# NEWS
* [2024.06.18] We have reverted to the non-vocab-expansion model. However, we have significantly increased the amount of pre-training data to 250GB.
* [2024.05.08] Vocab Expansion Model Update
* [2024.04.25] We released Bllossom v2.0, based on llama-3

## Example code

### Colab Tutorial
 - [Inference-Code-Link](https://colab.research.google.com/drive/1fBOzUVZ6NRKk_ugeoTbAOokWKqSN47IG?usp=sharing)

### Install Dependencies
```bash
pip install torch transformers==4.40.0 accelerate
```

### Python code with Pipeline
```python
import transformers
import torch

model_id = "MLP-KTLim/llama-3-Korean-Bllossom-8B"

pipeline = transformers.pipeline(
    "text-generation",
    model=model_id,
    model_kwargs={"torch_dtype": torch.bfloat16},
    device_map="auto",
)

pipeline.model.eval()

PROMPT = '''You are a helpful AI assistant. Please answer the user's questions kindly. 당신은 유능한 AI 어시스턴트 입니다. 사용자의 질문에 대해 친절하게 답변해주세요.'''
instruction = "서울의 유명한 관광 코스를 만들어줄래?"

messages = [
    {"role": "system", "content": f"{PROMPT}"},
    {"role": "user", "content": f"{instruction}"}
    ]

prompt = pipeline.tokenizer.apply_chat_template(
        messages, 
        tokenize=False, 
        add_generation_prompt=True
)

terminators = [
    pipeline.tokenizer.eos_token_id,
    pipeline.tokenizer.convert_tokens_to_ids("<|eot_id|>")
]

outputs = pipeline(
    prompt,
    max_new_tokens=2048,
    eos_token_id=terminators,
    do_sample=True,
    temperature=0.6,
    top_p=0.9
)

print(outputs[0]["generated_text"][len(prompt):])
```
```
# 물론이죠! 서울은 다양한 문화와 역사, 자연을 겸비한 도시로, 많은 관광 명소를 자랑합니다. 여기 서울의 유명한 관광 코스를 소개해 드릴게요.

### 코스 1: 역사와 문화 탐방

1. **경복궁**
   - 서울의 대표적인 궁궐로, 조선 왕조의 역사와 문화를 체험할 수 있는 곳입니다.

2. **북촌 한옥마을**
   - 전통 한옥이 잘 보존된 마을로, 조선시대의 생활상을 느낄 수 있습니다.

3. **인사동**
   - 전통 문화와 현대 예술이 공존하는 거리로, 다양한 갤러리와 전통 음식점이 있습니다.

4. **청계천**
   - 서울의 중심에 위치한 천문으로, 조깅과 산책을 즐길 수 있는 곳입니다.

### 코스 2: 자연과 쇼핑

1. **남산 서울타워**
   - 서울의 전경을 한눈에 볼 수 있는 곳으로, 특히 저녁 시간대에 일몰을 감상하는 것이 좋습니다.

2. **명동**
   - 쇼핑과 음식점이 즐비한 지역으로, 다양한 브랜드와 전통 음식을 맛볼 수 있습니다.

3. **한강공원**
   - 서울의 주요 공원 중 하나로, 조깅, 자전거 타기, 배낭 여행을 즐길 수 있습니다.

4. **홍대**
   - 젊은이들이 즐겨 찾는 지역으로, 다양한 카페, 레스토랑, 클럽이 있습니다.

### 코스 3: 현대와 전통의 조화

1. **동대문 디자인 플라자 (DDP)**
   - 현대적인 건축물로, 다양한 전시와 이벤트가 열리는 곳입니다.

2. **이태원**
   - 다양한 국제 음식과 카페가 있는 지역으로, 다양한 문화를 경험할 수 있습니다.

3. **광화문**
   - 서울의 중심에 위치한 광장으로, 다양한 공연과 행사가 열립니다.

4. **서울랜드**
   - 서울 외곽에 위치한 테마파크로, 가족단위 관광객들에게 인기 있는 곳입니다.

이 코스들은 서울의 다양한 면모를 경험할 수 있도록 구성되어 있습니다. 각 코스마다 시간을 조절하고, 개인의 관심사에 맞게 선택하여 방문하면 좋을 것 같습니다. 즐거운 여행 되세요!
```

### Python code with AutoModel
```python

import os
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

model_id = 'MLP-KTLim/llama-3-Korean-Bllossom-8B'

tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.bfloat16,
    device_map="auto",
)

model.eval()

PROMPT = '''You are a helpful AI assistant. Please answer the user's questions kindly. 당신은 유능한 AI 어시스턴트 입니다. 사용자의 질문에 대해 친절하게 답변해주세요.'''
instruction = "서울의 유명한 관광 코스를 만들어줄래?"

messages = [
    {"role": "system", "content": f"{PROMPT}"},
    {"role": "user", "content": f"{instruction}"}
    ]

input_ids = tokenizer.apply_chat_template(
    messages,
    add_generation_prompt=True,
    return_tensors="pt"
).to(model.device)

terminators = [
    tokenizer.eos_token_id,
    tokenizer.convert_tokens_to_ids("<|eot_id|>")
]

outputs = model.generate(
    input_ids,
    max_new_tokens=2048,
    eos_token_id=terminators,
    do_sample=True,
    temperature=0.6,
    top_p=0.9
)

print(tokenizer.decode(outputs[0][input_ids.shape[-1]:], skip_special_tokens=True))
```
```
# 물론이죠! 서울은 다양한 문화와 역사, 자연을 겸비한 도시로, 많은 관광 명소를 자랑합니다. 여기 서울의 유명한 관광 코스를 소개해 드릴게요.

### 코스 1: 역사와 문화 탐방

1. **경복궁**
   - 서울의 대표적인 궁궐로, 조선 왕조의 역사와 문화를 체험할 수 있는 곳입니다.

2. **북촌 한옥마을**
   - 전통 한옥이 잘 보존된 마을로, 조선시대의 생활상을 느낄 수 있습니다.

3. **인사동**
   - 전통 문화와 현대 예술이 공존하는 거리로, 다양한 갤러리와 전통 음식점이 있습니다.

4. **청계천**
   - 서울의 중심에 위치한 천문으로, 조깅과 산책을 즐길 수 있는 곳입니다.

### 코스 2: 자연과 쇼핑

1. **남산 서울타워**
   - 서울의 전경을 한눈에 볼 수 있는 곳으로, 특히 저녁 시간대에 일몰을 감상하는 것이 좋습니다.

2. **명동**
   - 쇼핑과 음식점이 즐비한 지역으로, 다양한 브랜드와 전통 음식을 맛볼 수 있습니다.

3. **한강공원**
   - 서울의 주요 공원 중 하나로, 조깅, 자전거 타기, 배낭 여행을 즐길 수 있습니다.

4. **홍대**
   - 젊은이들이 즐겨 찾는 지역으로, 다양한 카페, 레스토랑, 클럽이 있습니다.

### 코스 3: 현대와 전통의 조화

1. **동대문 디자인 플라자 (DDP)**
   - 현대적인 건축물로, 다양한 전시와 이벤트가 열리는 곳입니다.

2. **이태원**
   - 다양한 국제 음식과 카페가 있는 지역으로, 다양한 문화를 경험할 수 있습니다.

3. **광화문**
   - 서울의 중심에 위치한 광장으로, 다양한 공연과 행사가 열립니다.

4. **서울랜드**
   - 서울 외곽에 위치한 테마파크로, 가족단위 관광객들에게 인기 있는 곳입니다.

이 코스들은 서울의 다양한 면모를 경험할 수 있도록 구성되어 있습니다. 각 코스마다 시간을 조절하고, 개인의 관심사에 맞게 선택하여 방문하면 좋을 것 같습니다. 즐거운 여행 되세요!
```



## Citation
**Language Model**
```text
@misc{bllossom,
  author = {ChangSu Choi, Yongbin Jeong, Seoyoon Park, InHo Won, HyeonSeok Lim, SangMin Kim, Yejee Kang, Chanhyuk Yoon, Jaewan Park, Yiseul Lee, HyeJin Lee, Younggyun Hahm, Hansaem Kim, KyungTae Lim},
  title = {Optimizing Language Augmentation for Multilingual Large Language Models: A Case Study on Korean},
  year = {2024},
  journal = {LREC-COLING 2024},
  paperLink = {\url{https://arxiv.org/pdf/2403.10882}},
 },
}
```

**Vision-Language Model**
```text
@misc{bllossom-V,
  author = {Dongjae Shin, Hyunseok Lim, Inho Won, Changsu Choi, Minjun Kim, Seungwoo Song, Hangyeol Yoo, Sangmin Kim, Kyungtae Lim},
  title = {X-LLaVA: Optimizing Bilingual Large Vision-Language Alignment},
  year = {2024},
  publisher = {GitHub},
  journal = {NAACL 2024 findings},
  paperLink = {\url{https://arxiv.org/pdf/2403.11399}},
 },
}
```

## Contact
 - 임경태(KyungTae Lim), Professor at Seoultech. `ktlim@seoultech.ac.kr`
 - 함영균(Younggyun Hahm), CEO of Teddysum. `hahmyg@teddysum.ai`
 - 김한샘(Hansaem Kim), Professor at Yonsei. `khss@yonsei.ac.kr`

## Contributor
 - 최창수(Chansu Choi), choics2623@seoultech.ac.kr
 - 김상민(Sangmin Kim), sangmin9708@naver.com
 - 원인호(Inho Won), wih1226@seoultech.ac.kr
 - 김민준(Minjun Kim), mjkmain@seoultech.ac.kr 
 - 송승우(Seungwoo Song), sswoo@seoultech.ac.kr
 - 신동재(Dongjae Shin), dylan1998@seoultech.ac.kr
 - 임현석(Hyeonseok Lim), gustjrantk@seoultech.ac.kr
 - 육정훈(Jeonghun Yuk), usually670@gmail.com
 - 유한결(Hangyeol Yoo), 21102372@seoultech.ac.kr
 - 송서현(Seohyun Song), alexalex225225@gmail.com