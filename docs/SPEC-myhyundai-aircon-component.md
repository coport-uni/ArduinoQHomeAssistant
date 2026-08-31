# 개발 사양서: myhyundai_aircon 홈어시스턴트 커스텀 컴포넌트

문서 버전: 1.0
작성일: 2026-09-01
구현 주체: Claude Code
전제: 기존 홈어시스턴트 프로젝트에 커스텀 컴포넌트를 추가하는 형태로 개발한다.

---

## 0. 구현자를 위한 최우선 안내

이 사양서에는 **미확정 값**이 존재한다. 마이현대 위젯의 resource-id, 결과 알림 문구, 화면 해상도 실측값은 실기기에서 덤프를 떠야 확정된다. 구현자는 이 값들을 코드에 하드코딩하지 않는다. 대신 8장에 정의된 레시피 JSON 파일로 외부화하고, 사용자가 나중에 파일만 수정하면 동작이 바뀌도록 만든다.

구현 순서는 11장을 따른다. 미확정 값 없이도 1단계부터 4단계까지는 완결 가능하도록 설계되어 있다.

---

## 1. 목적과 범위

### 1.1 목적

홈어시스턴트에서 ADB 를 경유해 전용 안드로이드 기기의 마이현대 홈 화면 위젯을 조작함으로써, 차량의 원격 공조를 켜고 끄는 스위치 엔티티를 제공한다.

### 1.2 배경

국내 현대차 원격 제어는 다음 이유로 API 직접 호출이 불가능하다.

| 경로 | 상태 |
|---|---|
| Hyundai Developers 공식 API | 조회 전용, 제어 엔드포인트 없음 |
| 스마트싱스 홈투카 | ccNC 또는 ccIC27 탑재 차량만 지원, 대상 차량 미해당 |
| hyundai_kia_connect_api | 한국 리전 미지원 |
| bluelinky | 한국 리전 미지원 |

따라서 마이현대 앱 UI 를 조작하는 것이 유일한 실행 경로이며, 그중 홈 화면 위젯 조작이 앱 내부 화면 조작보다 단계가 짧고 앱 업데이트에 강하다.

### 1.3 범위

| 구분 | 항목 | 포함 |
|---|---|---|
| 필수 | 위젯 탭으로 공조 실행 | 포함 |
| 필수 | 실행 결과 판정 및 엔티티 반영 | 포함 |
| 필수 | 안전 가드, 쿨다운, 최대 유지 시간 | 포함 |
| 필수 | UI 덤프 수집 서비스 | 포함 |
| 선택 | 앱 전체 화면 경로 대체 시퀀스 | 포함, 레시피로 정의 |
| 선택 | 문 잠금과 해제 | 레시피 확장으로 대응 |
| 제외 | 차량 상태 조회 | 별도 REST 센서가 담당 |
| 제외 | 디지털키, 결제, 계정 조작 | 영구 제외 |

### 1.4 비목표

컴포넌트는 차량 상태를 알지 못한다. 공조가 실제로 켜져 있는지 ADB 로 확인할 방법이 없으므로 스위치는 낙관적 상태로 동작하며 `assumed_state` 를 참으로 선언한다.

---

## 2. 시스템 구성

```
[홈어시스턴트 코어]
  custom_components/myhyundai_aircon
      |
      |  adb-shell TCP, 포트 5555, adbkey 인증
      v
[전용 안드로이드 기기]  갤럭시 Z 폴드3, 커버 화면 고정
      |
      |  런처 홈 화면의 마이현대 위젯 탭
      v
[마이현대 앱]  com.hyundai.oneapp.kr
      |
      v
[블루링크 서버] --> [차량]
      |
      |  실행 결과 푸시 알림
      v
[dumpsys notification --noredact 폴링] --> 결과 판정
```

외부 의존 요소로 Hyundai Developers API 기반 배터리 잔량 센서가 있으나, 컴포넌트는 이를 직접 호출하지 않고 엔티티 ID 로 참조만 한다.

---

## 3. 대상 환경

| 항목 | 값 |
|---|---|
| 홈어시스턴트 최소 버전 | 2025.1 이상 |
| Python | 홈어시스턴트 코어가 요구하는 버전을 따름 |
| 통합 유형 | 커스텀 컴포넌트, HACS 배포 가능 구조 |
| IoT 클래스 | `local_polling` |
| 설정 방식 | Config Flow, YAML 설정 미지원 |
| 대상 기기 OS | 안드로이드 12 이상 |
| 대상 앱 패키지 | `com.hyundai.oneapp.kr` |

### 3.1 ADB 라이브러리

`adb-shell` 을 사용한다. 홈어시스턴트 코어의 `androidtv` 통합이 동일 라이브러리를 사용하므로 **버전 충돌을 반드시 확인한다**. 구현자는 현재 홈어시스턴트가 고정하고 있는 `adb-shell` 버전을 먼저 조사하고, `manifest.json` 의 `requirements` 에 동일 버전을 명시한다. 다른 버전을 요구하면 설치 충돌이 발생한다.

비동기 API 를 우선 사용한다. `adb_shell.adb_device_async.AdbDeviceTcpAsync` 와 `adb_shell.auth.keygen` 을 쓰고, 동기 호출이 불가피한 구간은 `hass.async_add_executor_job` 으로 감싼다. 이벤트 루프를 블로킹하는 코드는 허용하지 않는다.

---

## 4. 파일 구조

```
custom_components/myhyundai_aircon/
    __init__.py
    manifest.json
    const.py
    config_flow.py
    coordinator.py
    adb_client.py
    recipe.py
    executor.py
    notification.py
    switch.py
    sensor.py
    binary_sensor.py
    services.yaml
    strings.json
    translations/
        en.json
        ko.json
    recipes/
        default.json
```

| 모듈 | 책임 |
|---|---|
| `adb_client.py` | ADB 연결 수립, 재연결, `shell` 명령 실행, 연결 상태 보고 |
| `recipe.py` | 레시피 JSON 로드, 스키마 검증, 스텝 객체화 |
| `executor.py` | 레시피 스텝 실행, UI 덤프 파싱, 노드 탐색, 좌표 계산 |
| `notification.py` | `dumpsys notification --noredact` 파싱, 결과 문구 매칭 |
| `coordinator.py` | 기기 온라인 상태 폴링, 마지막 실행 결과 보관 |
| `switch.py` | 공조 스위치 엔티티 |
| `sensor.py` | 마지막 실행 결과, 마지막 오류 코드 센서 |
| `binary_sensor.py` | 기기 연결 상태 |

---

## 5. 설정 항목

### 5.1 Config Flow 최초 설정

| 키 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `host` | str | 필수 | 없음 | 안드로이드 기기 IP, DHCP 예약으로 고정된 주소 |
| `port` | int | 선택 | 5555 | ADB TCP 포트 |
| `adbkey_path` | str | 선택 | `.storage/myhyundai_aircon_adbkey` | 없으면 신규 생성 |
| `device_name` | str | 선택 | `myhyundai` | 엔티티 이름 접두사 |

설정 단계에서 반드시 연결 테스트를 수행한다. 연결 성공 시 `wm size` 를 실행해 기준 해상도를 읽고 `baseline_screen` 으로 저장한다. 사용자가 값을 입력하지 않는다.

연결 실패 시 오류를 다음과 같이 구분해 안내한다.

| 상황 | 오류 키 | 사용자 안내 |
|---|---|---|
| TCP 연결 불가 | `cannot_connect` | IP 와 `adb tcpip 5555` 실행 여부 확인 |
| 인증 거부 | `auth_rejected` | 기기 화면의 USB 디버깅 허용 대화상자 확인 |
| shell 응답 이상 | `invalid_device` | 대상 기기가 맞는지 확인 |

### 5.2 Options Flow 조정 가능 항목

| 키 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `recipe_file` | str | `default.json` | 사용할 레시피 파일명 |
| `battery_sensor` | str | 없음 | 배터리 잔량 센서 엔티티 ID |
| `battery_floor_pct` | int | 40 | 이 값 미만이면 실행 차단 |
| `command_min_gap_sec` | int | 3 | 직전 명령 후 최소 간격 |
| `cooldown_sec` | int | 60 | 연속 실행 방지 쿨다운 |
| `aircon_max_minutes` | int | 10 | 차량 측 최대 유지 시간, 자동 OFF 타이머 |
| `notification_timeout_sec` | int | 60 | 결과 알림 대기 상한 |
| `sequence_timeout_sec` | int | 90 | 전체 시퀀스 상한 |
| `retry_max` | int | 2 | 실패 재시도 횟수 |
| `retry_gap_sec` | int | 30 | 재시도 간격 |
| `screen_check_enabled` | bool | 참 | 실행 전 해상도 검증 |
| `dump_on_failure` | bool | 참 | 실패 시 덤프 자동 저장 |

---

## 6. 엔티티 정의

### 6.1 스위치

| 항목 | 값 |
|---|---|
| 엔티티 ID | `switch.myhyundai_aircon` |
| 플랫폼 | `switch` |
| `assumed_state` | 참 |
| `device_class` | 없음 |
| ON 동작 | `aircon_on` 레시피 실행 |
| OFF 동작 | `aircon_off` 레시피 실행 |
| 자동 OFF | `aircon_max_minutes` 경과 시 상태를 OFF 로 되돌림 |

`aircon_off` 레시피가 정의되지 않은 경우 OFF 호출은 차량에 명령을 보내지 않고 내부 상태만 OFF 로 되돌린다. 이때 로그에 경고를 남긴다. 위젯에 끄기 버튼이 없을 가능성이 있으므로 이 동작은 필수 구현이다.

추가 속성으로 다음을 노출한다.

| 속성 | 설명 |
|---|---|
| `last_result` | `success` 또는 `failure` |
| `last_error_code` | 오류 코드 문자열 |
| `last_started` | 마지막 ON 성공 시각 |
| `expires_at` | 자동 OFF 예정 시각 |
| `screen_checked` | 실행 시점 해상도 |

### 6.2 센서

| 엔티티 ID | 상태값 | 비고 |
|---|---|---|
| `sensor.myhyundai_last_result` | `success`, `failure`, `unknown` | 실행 이력 |
| `sensor.myhyundai_last_error` | 오류 코드 또는 `none` | 진단용 |
| `sensor.myhyundai_last_notification` | 알림 원문 텍스트 | 최대 255자 절단 |

### 6.3 이진 센서

| 엔티티 ID | 의미 |
|---|---|
| `binary_sensor.myhyundai_device_connected` | ADB 연결 상태, `connectivity` 클래스 |

---

## 7. 서비스

`services.yaml` 에 다음 3개를 정의한다.

### 7.1 `myhyundai_aircon.capture_dump`

현재 화면의 UI 계층과 스크린샷을 저장한다. 레시피 작성과 장애 분석의 핵심 도구다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `label` | str | 선택 | 파일명에 붙일 식별자 |

저장 경로는 `config/myhyundai_aircon_dumps/YYYYMMDD-HHMMSS-<label>.xml` 과 동일 이름의 `.png` 다. 서비스 완료 시 저장 경로를 로그에 남기고 영구 알림으로도 표시한다.

### 7.2 `myhyundai_aircon.run_sequence`

레시피에 정의된 임의 시퀀스를 실행한다. 스위치를 거치지 않는 확장 경로다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `sequence` | str | 필수 | 레시피 내 시퀀스 키 |
| `ignore_guards` | bool | 선택 | 안전 가드 무시, 기본 거짓 |

### 7.3 `myhyundai_aircon.reload_recipe`

레시피 JSON 을 다시 읽는다. 홈어시스턴트 재시작 없이 시퀀스를 수정하기 위함이다.

---

## 8. 레시피 정의

### 8.1 설계 원칙

시퀀스는 코드가 아니라 데이터다. 마이현대 앱이 업데이트되어 UI 가 바뀌면 사용자는 JSON 파일만 수정하고 `reload_recipe` 를 호출한다. 파이썬 코드 수정은 필요하지 않다.

### 8.2 스키마

```json
{
  "version": 1,
  "baseline_screen": "832x2268",
  "package": "com.hyundai.oneapp.kr",
  "sequences": {
    "aircon_on": {
      "description": "홈 화면 위젯의 시동 공조 버튼 탭",
      "steps": []
    }
  }
}
```

### 8.3 스텝 액션 타입

구현자는 아래 액션을 모두 지원해야 한다.

| `action` | 필수 필드 | 동작 |
|---|---|---|
| `keyevent` | `key` | `input keyevent <key>` 실행 |
| `wake` | 없음 | 화면 상태 확인 후 꺼져 있으면 깨움 |
| `home` | 없음 | 홈 키 입력 후 런처 포커스 확인 |
| `launch_app` | `package` | `monkey` 또는 `am start` 로 앱 실행 |
| `stop_app` | `package` | `am force-stop` 실행 |
| `wait_focus` | `pattern`, `timeout` | `dumpsys window` 의 현재 포커스가 패턴과 일치할 때까지 대기 |
| `wait_node` | `match`, `timeout` | UI 덤프에서 노드가 나타날 때까지 대기 |
| `tap_node` | `match` | 노드 중심 좌표 계산 후 탭 |
| `tap_ratio` | `x`, `y` | 화면 비율 기준 좌표 탭, 최후 수단 |
| `swipe` | `x1`,`y1`,`x2`,`y2`,`duration` | 스와이프 |
| `sleep` | `seconds` | 고정 대기, 사용 최소화 |
| `assert_screen` | 없음 | 현재 해상도와 `baseline_screen` 비교 |
| `await_notification` | `success_contains`, `failure_contains`, `timeout` | 알림 폴링으로 결과 판정 |

모든 스텝은 공통 선택 필드 `optional` 을 가진다. 참이면 실패해도 다음 스텝으로 진행한다. 확인 팝업처럼 나타날 수도 있고 아닐 수도 있는 화면에 사용한다.

### 8.4 노드 매칭 규칙

`match` 객체는 다음 키를 조합한다. 여러 키가 주어지면 모두 만족하는 노드를 찾는다.

| 키 | 의미 |
|---|---|
| `resource_id` | `resource-id` 속성 완전 일치 |
| `text` | `text` 속성 완전 일치 |
| `text_contains` | `text` 속성 부분 일치 |
| `content_desc` | `content-desc` 속성 완전 일치 |
| `class` | `class` 속성 완전 일치 |
| `package` | `package` 속성 완전 일치 |
| `index` | 조건을 만족하는 노드 중 N 번째, 기본 0 |

매칭 결과가 0개이면 `E_UNKNOWN_SCREEN`, 2개 이상인데 `index` 가 없으면 첫 번째를 쓰되 경고 로그를 남긴다.

### 8.5 기본 레시피 초안

아래는 **자리표시자**다. `RESOURCE_ID_PLACEHOLDER` 와 알림 문구는 실기기 덤프 후 사용자가 채운다. 구현자는 이 파일을 그대로 `recipes/default.json` 으로 배포하고, 자리표시자가 남아 있으면 실행 시 `E_RECIPE_INCOMPLETE` 를 반환하도록 검증한다.

```json
{
  "version": 1,
  "baseline_screen": "AUTO",
  "package": "com.hyundai.oneapp.kr",
  "sequences": {
    "aircon_on": {
      "description": "홈 화면 위젯 시동 공조 실행",
      "steps": [
        { "action": "assert_screen" },
        { "action": "wake" },
        { "action": "home" },
        { "action": "wait_focus", "pattern": "Launcher", "timeout": 5 },
        {
          "action": "tap_node",
          "match": { "text_contains": "TEXT_PLACEHOLDER" },
          "timeout": 5
        },
        {
          "action": "wait_node",
          "match": { "text_contains": "CONFIRM_TEXT_PLACEHOLDER" },
          "timeout": 5,
          "optional": true
        },
        {
          "action": "tap_node",
          "match": { "text_contains": "CONFIRM_TEXT_PLACEHOLDER" },
          "optional": true
        },
        {
          "action": "await_notification",
          "success_contains": ["SUCCESS_TEXT_PLACEHOLDER"],
          "failure_contains": ["FAILURE_TEXT_PLACEHOLDER"],
          "timeout": 60
        }
      ]
    },
    "aircon_off": {
      "description": "미확정. 위젯에 끄기 버튼이 없으면 앱 경로로 정의한다.",
      "steps": []
    }
  }
}
```

---

## 9. 실행 플로우

### 9.1 상태 전이

```
IDLE
 |  스위치 ON 호출 또는 run_sequence 서비스
 v
GUARD_CHECK        쿨다운, 최소 간격, 배터리 잔량, 레시피 완결성
 |  통과                       |  미통과
 v                             v
CONNECT                      ABORT
 |  ADB 연결 확인 및 필요 시 재연결
 v
SCREEN_CHECK       assert_screen 스텝
 |
 v
RUN_STEPS          레시피 스텝 순차 실행
 |
 v
AWAIT_RESULT       알림 폴링, 1초 간격
 |  성공          |  실패          |  타임아웃
 v                v                v
DONE            RETRY            RETRY
                  |  retry_max 초과
                  v
                FAILED
```

### 9.2 알림 판정 절차

1. 시퀀스 시작 직전에 마이현대 패키지의 기존 알림을 제거한다. 이전 실행의 알림을 새 결과로 오인하는 것을 막기 위함이다.
2. 실행 후 1초 간격으로 `dumpsys notification --noredact` 를 실행한다.
3. 출력에서 `pkg=com.hyundai.oneapp.kr` 블록만 추출한다.
4. 블록 내 텍스트에 `failure_contains` 항목이 하나라도 포함되면 실패로 판정한다. 실패 판정을 성공 판정보다 먼저 수행한다.
5. `success_contains` 항목이 포함되면 성공으로 판정한다.
6. `timeout` 까지 어느 쪽도 나타나지 않으면 `E_TIMEOUT` 이다.

`dumpsys` 출력 형식은 안드로이드 버전에 따라 다르므로, 파서는 특정 형식에 강하게 의존하지 말고 패키지 블록 안의 모든 문자열을 모아 부분 일치로 검사한다.

### 9.3 오류 코드

| 코드 | 원인 | 재시도 | 후속 |
|---|---|---|---|
| `E_RECIPE_INCOMPLETE` | 레시피에 자리표시자 잔존 | 안 함 | 영구 알림 |
| `E_COOLDOWN` | 쿨다운 중 | 안 함 | 로그만 |
| `E_MIN_GAP` | 최소 간격 미충족 | 안 함 | 로그만 |
| `E_BATTERY_LOW` | 배터리 잔량 미달 | 안 함 | 영구 알림 |
| `E_DEVICE_OFFLINE` | ADB 연결 실패 | 1회 | 재연결 시도 |
| `E_SCREEN_MISMATCH` | 해상도 불일치 | 안 함 | 영구 알림, 폴딩 상태 확인 요청 |
| `E_SESSION_EXPIRED` | 로그인 화면 감지 | 안 함 | 영구 알림, 수동 재로그인 |
| `E_UNKNOWN_SCREEN` | 노드 미발견 | 안 함 | 덤프 자동 저장 |
| `E_TIMEOUT` | 결과 미수신 | 최대 2회 | 앱 강제 종료 후 재시도 |
| `E_VEHICLE_FAIL` | 실패 알림 수신 | 최대 2회 | 30초 후 재시도 |

`E_SESSION_EXPIRED` 판정은 UI 덤프에 로그인 화면 특징 문자열이 있는지로 수행한다. 해당 문자열은 레시피의 `login_markers` 배열로 외부화한다.

### 9.4 이벤트 발행

실행이 끝나면 `myhyundai_aircon_result` 이벤트를 발행한다. 사용자가 자동화에서 결과를 받아 알림이나 로깅에 쓸 수 있게 한다.

```json
{
  "sequence": "aircon_on",
  "result": "success",
  "code": null,
  "elapsed_sec": 34.2,
  "attempt": 1,
  "screen_checked": "832x2268",
  "notification_text": "…"
}
```

---

## 10. 비기능 요구사항

### 10.1 동시성

시퀀스 실행은 `asyncio.Lock` 으로 직렬화한다. 두 자동화가 동시에 스위치를 켜도 실행은 하나만 진행되고 나머지는 `E_COOLDOWN` 으로 즉시 반환한다.

### 10.2 로깅

| 레벨 | 내용 |
|---|---|
| `debug` | 실행한 shell 명령 전문, 매칭된 노드 정보 |
| `info` | 시퀀스 시작과 종료, 결과, 소요 시간 |
| `warning` | 선택 스텝 실패, 노드 다중 매칭, `aircon_off` 미정의 |
| `error` | 오류 코드를 동반한 실패 |

`adbkey` 내용과 알림 원문 중 개인정보로 보일 수 있는 부분은 `debug` 레벨에서도 출력하지 않는다.

### 10.3 재연결 정책

ADB 연결이 끊기면 지수 백오프로 재연결한다. 간격은 5초, 15초, 45초, 이후 60초 고정이다. 재연결 시도는 코디네이터가 담당하며 시퀀스 실행 중에는 1회만 시도한다.

### 10.4 성능

시퀀스 1회 실행의 목표 소요는 알림 대기를 제외하고 15초 이내다. UI 덤프는 1회 실행에 1초 내외가 걸리므로 `wait_node` 폴링 간격은 1초로 두고 불필요한 덤프를 줄인다.

---

## 11. 구현 순서

각 단계는 독립적으로 검증 가능해야 한다.

| 단계 | 산출물 | 완료 기준 | 미확정 값 필요 |
|---|---|---|---|
| 1 | `adb_client.py`, `manifest.json` | 파이썬 단위 테스트에서 mock 연결 성공 | 불필요 |
| 2 | `config_flow.py` | UI 에서 통합 추가 성공, 해상도 자동 저장 | 불필요 |
| 3 | `capture_dump` 서비스 | 실기기 덤프 XML 과 PNG 저장 확인 | 불필요 |
| 4 | `recipe.py`, `executor.py` | 자리표시자 검증과 스텝 실행기 단위 테스트 통과 | 불필요 |
| 5 | 레시피 실값 채우기 | 3단계 덤프로 위젯 노드 식별자 확정 | **필요** |
| 6 | `notification.py` | 성공과 실패 알림 문구 확보 후 판정 동작 | **필요** |
| 7 | `switch.py`, `sensor.py`, `binary_sensor.py` | 엔티티 생성 및 상태 반영 | 불필요 |
| 8 | 안전 가드, 재시도 | 13장 테스트 전 항목 통과 | 불필요 |
| 9 | 문서와 번역 | README, 한국어 및 영어 번역 완비 | 불필요 |

구현자는 5단계와 6단계 이전에 멈추고 사용자에게 덤프 실행을 요청한다. 값을 추측해서 채우지 않는다.

---

## 12. 사용자 준비 사항

컴포넌트가 동작하려면 기기 측 설정이 선행되어야 한다. README 에 다음을 그대로 싣는다.

| 분류 | 항목 | 설정값 |
|---|---|---|
| 개발자 옵션 | USB 디버깅 | 켜기 |
| 개발자 옵션 | 충전 중 화면 켜짐 유지 | 켜기 |
| 개발자 옵션 | 애니메이션 배율 3종 | 0.5배 |
| 화면 | 화면 자동 꺼짐 | 최대값 |
| 화면 | 잠금 화면 | 없음 |
| 화면 | 화면 회전 | 세로 고정 |
| 폴더블 | 폴딩 상태 | 접힘 고정, 커버 화면 사용 |
| 런처 | 마이현대 위젯 | 홈 화면 첫 페이지에 배치 |
| 런처 | 홈 화면 페이지 | 위젯이 있는 페이지를 기본 페이지로 지정 |
| 배터리 | 마이현대 배터리 최적화 | 제외 |
| 배터리 | 충전 상한 | 지원 시 85퍼센트 |
| 네트워크 | IP | DHCP 예약으로 고정 |
| 시스템 | 자동 업데이트 | 끄기 |
| 앱 | 마이현대 자동 업데이트 | 끄기 |

ADB TCP 활성화 절차도 함께 안내한다. USB 로 연결한 PC 에서 `adb tcpip 5555` 를 1회 실행하면 기기가 재부팅될 때까지 TCP 연결이 유지된다. 기기를 재부팅하면 이 절차를 다시 수행해야 하므로, 전용 기기는 상시 가동하고 재부팅을 피한다.

---

## 13. 테스트 계획

### 13.1 단위 테스트

`pytest-homeassistant-custom-component` 를 사용한다. ADB 클라이언트는 mock 으로 대체하고, 미리 저장한 UI 덤프 XML 파일을 픽스처로 사용한다.

| 대상 | 검증 항목 |
|---|---|
| 레시피 로더 | 스키마 위반 감지, 자리표시자 감지 |
| 노드 매처 | 단일 매칭, 다중 매칭, 미매칭 |
| 좌표 계산 | `bounds` 문자열 파싱과 중심점 산출 |
| 알림 파서 | 성공, 실패, 미수신 3케이스 |
| 가드 | 쿨다운, 최소 간격, 배터리 미달 |
| 스위치 | 자동 OFF 타이머 동작 |

### 13.2 통합 테스트

실기기에서 수행한다.

| 번호 | 시나리오 | 만드는 방법 | 기대 결과 |
|---|---|---|---|
| T1 | 정상 실행 | 평시 실행 | `success` |
| T2 | 배터리 부족 | `battery_floor_pct` 를 99로 임시 상향 | `E_BATTERY_LOW` |
| T3 | 세션 만료 | 앱에서 로그아웃 후 실행 | `E_SESSION_EXPIRED` |
| T4 | 기기 오프라인 | 기기 와이파이 차단 | `E_DEVICE_OFFLINE` |
| T5 | 폴딩 상태 오류 | 기기를 펼친 상태로 실행 | `E_SCREEN_MISMATCH` |
| T6 | 화면 꺼짐 | 화면 수동 소등 후 실행 | 깨움 후 `success` |
| T7 | 연속 실행 | 3초 이내 재호출 | `E_MIN_GAP` |
| T8 | 결과 미수신 | 차량 통신 불가 상태에서 실행 | `E_TIMEOUT` 후 재시도 |
| T9 | 레시피 미완성 | 자리표시자 남긴 채 실행 | `E_RECIPE_INCOMPLETE` |
| T10 | 자동 OFF | ON 후 `aircon_max_minutes` 경과 | 상태가 OFF 로 전환 |

---

## 14. 미확정 항목

구현 전 또는 5단계 이전에 사용자가 실기기에서 확인해야 한다.

| 번호 | 항목 | 확인 방법 | 영향 |
|---|---|---|---|
| U1 | 마이현대 동시 로그인 허용 여부 | 전용 기기 로그인 후 주력 폰 상태 확인 | 계정 구조 |
| U2 | ADB 디버깅 활성 상태에서 앱 정상 동작 | 디버깅 켠 채 앱 실행 | 프로젝트 성립 여부 |
| U3 | 위젯 노드의 `resource-id` 와 `text` | `capture_dump` 실행 | `aircon_on` 레시피 |
| U4 | 위젯 탭 후 확인 팝업 유무 | 수동 조작 관찰 | 스텝 개수 |
| U5 | 성공 알림 문구 | 수동 실행 후 `dumpsys notification --noredact` | 결과 판정 |
| U6 | 실패 알림 문구 | 도어 열림 상태 등으로 실패 유발 후 확인 | 결과 판정 |
| U7 | 위젯에 공조 끄기 버튼 존재 여부 | 위젯 관찰 | `aircon_off` 정의 가능 여부 |
| U8 | 로그인 화면 특징 문자열 | 로그아웃 후 덤프 | `login_markers` |
| U9 | 커버 화면에서 위젯 렌더링 여부 | 접은 상태로 홈 화면 확인 | 폴딩 고정 방향 |

U2 가 부정이면 프로젝트 전체가 성립하지 않는다. 가장 먼저 확인한다.

---

## 15. 제약과 주의

1. 차량 원격 제어는 마지막 시동 종료 후 96시간 이내에만 가능하다. 컴포넌트는 이 시각을 알 수 없으므로 시간 초과에 따른 실패는 `E_VEHICLE_FAIL` 또는 `E_TIMEOUT` 으로 나타난다. 사용자가 원한다면 마지막 성공 실행 시각과 외부 주행거리 센서 변화를 조합해 자동화 단에서 별도 판단한다.
2. 원격 공조는 차량 측에서 최대 10분간 유지된다. 자동 OFF 타이머의 기본값은 이 값에 맞춘다.
3. 12V 배터리 보호를 위해 불필요한 반복 실행을 피한다. 쿨다운 기본값 60초를 낮추지 않도록 README 에 명시한다.
4. 본 컴포넌트는 비공식 수단이며 마이현대 앱의 UI 변경 시 동작이 중단될 수 있다. README 첫머리에 이 사실과 함께 계정 이용 약관을 사용자가 직접 확인해야 함을 밝힌다.
5. 개인 용도로만 사용한다. 배포 시에도 사용자 각자가 자신의 기기와 계정으로 운용하는 구조를 유지한다.
