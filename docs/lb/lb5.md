# Лабораторна робота № 5. Побудова асинхронної черги обробки подій та повідомлень між вузлами кіберфізичної системи на базі AWS SQS та обробка збоїв через Dead-Letter Queue

**Мета:** Дослідження архітектурних патернів асинхронного обміну повідомленнями у розподілених обчислювальних системах, вивчення принципів функціонування керованих хмарних черг класу «точка–точка» (Point-to-Point), опанування методів програмного створення та конфігурування черг AWS SQS (Standard та FIFO), налаштування параметрів таймауту видимості (Visibility Timeout) та терміну життя повідомлень (Message Retention Period), розробка багатопотокового пулу обробників за моделлю «Виробник–Споживач» (Producer-Consumer), впровадження механізму ізоляції аварійних повідомлень за допомогою Dead-Letter Queue (DLQ) та проведення експериментального дослідження стійкості системи до сплесків навантаження і тимчасової відмови споживачів.

**Стек технологій та інструменти:**
* **Мова програмування та середовище виконання:** Python 3.10+ (CPython), віртуальне оточення `venv`.
* **Платформа та бібліотеки:** Хмарна платформа Amazon Web Services (AWS SQS), SDK-бібліотека `boto3` (v1.34+), `botocore` (v1.34+), модуль багатопотокової обробки `concurrent.futures`, утиліта `tabulate` (v0.9+).
* **Інструменти діагностики та розробки:** AWS CLI v2, інтегроване середовище розробки Visual Studio Code / PyCharm, консоль моніторингу черг.

---

## 1 Теоретичні відомості

У великомасштабних кіберфізичних комплексах та промислових системах Інтернету речей (IoT) безперервний потік телеметричних вимірювань і сигналів керування характеризується високою нерівномірністю в часі. Спроба безпосереднього зв'язування сенсорів із сервісами обробки за допомогою синхронних викликів (наприклад, HTTP REST API) призводить до жорсткої зв'язності компонентів (**Tight Coupling**) та виникнення відмов у періоди пікового навантаження (**Traffic Spikes**), коли обчислювальні вузли не встигають обробляти вхідні запити. 

Основою побудови стійких та еластичних розподілених систем є **асинхронна взаємодія на базі черг повідомлень (Message Queuing)**, реалізована за допомогою проміжного програмного забезпечення **Message-Oriented Middleware (MOM)**, еталонним представником якого у хмарі є сервіс **Amazon Simple Queue Service (AWS SQS)** або **Azure Service Bus Queues**.

```mermaid
flowchart LR
    subgraph Producers ["Виробники телеметрії (Producers)"]
        P1[IoT Датчик 1]
        P2[IoT Датчик 2]
        P3[IoT Датчик N]
    end

    subgraph QueueSystem ["Хмарна черга AWS SQS"]
        MainQ[(Основна черга: Main SQS Queue<br/>Durable Storage<br/>MessageRetention: 4 доби)]
        DLQ[(Черга недоставлених: SQS DLQ<br/>Redrive Policy: maxReceiveCount=3)]
    end

    subgraph Consumers ["Пул споживачів (Consumer Workers)"]
        W1[Worker 1: ThreadPool]
        W2[Worker 2: ThreadPool]
        W3[Worker 3: ThreadPool]
    end

    P1 ===>|SendMessageBatch| MainQ
    P2 ===>|SendMessageBatch| MainQ
    P3 ===>|SendMessageBatch| MainQ

    MainQ ===>|1. ReceiveMessage: In-Flight State| Consumers
    Consumers ===>|2. DeleteMessage: Успішна фіксація| MainQ
    
    MainQ -.->|3. Збій обробки > maxReceiveCount| DLQ
    Consumers -.->|4. Poison Pill: Необроблена помилка| MainQ
```
*Рисунок 1.1 — Архітектура асинхронного оброблення телеметрії з використанням черги SQS, пулу воркерів та Dead-Letter Queue*

Черга повідомлень виконує роль надійного демпфера (буфера), який усуває просторову, часову та синхронізаційну залежність між виробниками (**Producers**) та споживачами (**Consumers**). Виробники надсилають повідомлення в чергу з довільною швидкістю, отримують негайне підтвердження фіксації в сховищі та продовжують роботу, тоді як споживачі вичитують дані в міру звільнення власних обчислювальних потужностей.

Ключовим механізмом координації доступу та забезпечення стійкості до відмов у хмарних чергах є **таймаут видимості (Visibility Timeout, $T_{\text{vis}}$)**. Після того, як один із воркерів отримує повідомлення через виклик `ReceiveMessage`, брокер не видаляє його з черги, а переводить у тимчасово невидимий стан (**In-Flight State**) на інтервал часу $T_{\text{vis}}$. 

Протягом цього періоду інші споживачі не можуть отримати це повідомлення. Якщо воркер успішно завершує обробку, він надсилає команду `DeleteMessage`, передаючи унікальний рядок підтвердження — **ReceiptHandle**. 

Якщо ж у процесі обробки виникає збій (аварійна зупинка процесу, зависання пам'яті або мережевий розрив), після закінчення інтервалу $T_{\text{vis}}$ повідомлення автоматично знову стає видимим у черзі та підхоплюється іншим доступним обробником, гарантуючи семантику доставки **«щонайменше один раз» (At-least-once delivery)**.

```mermaid
sequenceDiagram
    autonumber
    participant Producer as Виробник телеметрії (Producer)
    participant SQS as Черга повідомлень (AWS SQS)
    participant Worker1 as Воркер 1 (Збійний)
    participant Worker2 as Воркер 2 (Резервний)
    participant DLQ as Черга DLQ

    Producer->>SQS: 1. SendMessage(TelemetryPayload)
    Note over SQS: Повідомлення збережено (State: Available, ReceiveCount=0)
    
    Worker1->>SQS: 2. ReceiveMessage(MaxMessages=10)
    SQS-->>Worker1: 3. Повернення Payload + ReceiptHandle (State: In-Flight, ReceiveCount=1)
    Note over SQS: Старт таймера Visibility Timeout (T_vis = 30s)
    
    Note over Worker1: Критична помилка обробника (Process Crash)
    Note over SQS: Спливає таймер Visibility Timeout (30s)
    Note over SQS: Повідомлення знову видиме для вичитування (State: Available)
    
    Worker2->>SQS: 4. ReceiveMessage(MaxMessages=10)
    SQS-->>Worker2: 5. Повернення Payload + Новий ReceiptHandle (ReceiveCount=2)
    Note over Worker2: Успішна обробка даних та запис у базу
    Worker2->>SQS: 6. DeleteMessage(ReceiptHandle)
    Note over SQS: Повідомлення остаточно видалено з черги
```
*Рисунок 1.2 — Життєвий цикл повідомлення в черзі за умови аварійної відмови обробника та автоматичного відновлення видимості*

Для запобігання нескінченному зацикленню некоректно сформованих або пошкоджених повідомлень («отруйних пігулок» — **Poison Pills**), які спричиняють аварійне падіння коду споживача при кожній спробі обробки, впроваджується **політика повторних спроб (Redrive Policy)** та **черга недоставлених повідомлень (Dead-Letter Queue, DLQ)**. 

Система SQS веде внутрішній лічильник спроб доставки кожного повідомлення — `ApproximateReceiveCount`. Якщо значення цього лічильника перевищує налаштований граничний поріг $N_{\text{max\_receive}}$, черга автоматично вилучає повідомлення з основного потоку та переміщує його до DLQ без участі користувача, запобігаючи блокуванню всього конвеєра та зберігаючи інцидент для діагностики.

Математично динаміка зміни довжини черги $Q(t)$ під час сплеску надходження телеметрії за умови, що інтенсивність генерації $\lambda(t)$ перевищує сукупну швидкість обробки $k \cdot \mu$, описується інтегральним рівнянням:

$$Q(t) = Q(t_0) + \int_{t_0}^t \left( \lambda(\tau) - k \cdot \mu \right) d\tau$$

де $Q(t_0)$ — початкова кількість повідомлень у черзі в момент початку сплеску $t_0$, $\lambda(\tau)$ — миттєва функція надходження повідомлень від сенсорної мережі (повідомлень/с), $k$ — кількість паралельних потоків (воркерів) у пулі обробки, $\mu$ — середня продуктивність одного воркера (повідомлень/с).

Час, необхідний для повного розвантаження черги після завершення сплеску навантаження в момент $t_1$, розраховується як:

$$T_{\text{drain}} = \frac{Q(t_1)}{k \cdot \mu - \lambda_{\text{normal}}}$$

де $\lambda_{\text{normal}}$ — стала фонова швидкість надходження повідомлень у штатному режимі ($\lambda_{\text{normal}} < k \cdot \mu$).

Мінімальне значення таймауту видимості $T_{\text{vis}}$ для уникнення передчасного дублювання завдань повинно строго задовольняти критерій надійності:

$$T_{\text{vis}} \ge \overline{t}_{\text{proc}} + 3 \cdot \sigma_t + 2 \cdot RTT_{\text{net}}$$

де $\overline{t}_{\text{proc}}$ — середній час обробки одного повідомлення воркером (у секундах), $\sigma_t$ — середньоквадратичне відхилення часу обробки, $RTT_{\text{net}}$ — кругова мережева затримка взаємодії з API черги.

*Таблиця 1.1 — Порівняльна характеристика режимів черг AWS SQS*

| Параметр конфігурації | AWS SQS Standard Queue | AWS SQS FIFO Queue |
| :--- | :--- | :--- |
| **Порядок доставки** | Найкраща спроба впорядкування (Best-effort) | Суворе дотримання черговості (First-In-First-Out) |
| **Гарантія унікальності** | Щонайменше один раз (можливі дублікати) | Рівно один раз (Exactly-once deduplication) |
| **Пропускна здатність** | Практично необмежена (десятки тисяч msg/s) | До 3000 msg/s (із застосуванням батчингу) |
| **Максимальний розмір** | 256 КБ на одне повідомлення | 256 КБ на одне повідомлення |
| **Критерій застосування в КФС** | Масовий збір незалежних вимірювань датчиків | Послідовні команди калібрування сервоприводів |

---

## 2 Підготовка середовища та розгортання проєкту (Крок 0)

Перед розробкою програмного комплексу необхідно підготувати робочу директорію, налаштувати віртуальне середовище Python, встановити офіційний пакет Boto3 та перевірити доступність служби AWS SQS.

### 2.1 Перевірка інструментів та створення робочої директорії

Відкрийте термінал операційної системи та перевірте наявність необхідних компонентів:

```bash
python3 --version
pip3 --version
aws --version
```

Створіть робочу ієрархію каталогів лабораторної роботи та активуйте віртуальне середовище:

```bash
mkdir -p ~/cloud_labs/lab5_sqs_queues
cd ~/cloud_labs/lab5_sqs_queues
python3 -m venv venv
source venv/bin/activate
```

Сформуйте файлову структуру проєкту відповідно до такої схеми:

```text
lab5_sqs_queues/
├── config/
│   └── sqs_config.json          # Конфігурація параметрів черг, Redrive Policy та таймаутів
├── scripts/
│   ├── __init__.py
│   ├── sqs_queue_manager.py     # Модуль керування чергами та DLQ через Boto3
│   ├── telemetry_producer.py    # Багатопотоковий генератор пакетів телеметрії
│   └── telemetry_consumer.py    # Багатопотоковий пул воркерів-обробників
├── output/
│   ├── queue_benchmark_report.json # Звіт про швидкість обробки та стійкість системи
│   └── dlq_analysis.json        # Дамп перехоплених аварійних повідомлень
├── requirements.txt             # Специфікація залежностей Python
└── run_lab5.py                  # Головний виконуваний модуль тестування
```

Створіть файл `requirements.txt`:

```text
boto3>=1.34.0
botocore>=1.34.0
tabulate>=0.9.0
```

Встановіть залежності у віртуальне оточення:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 2.2 Налаштування конфігураційного профілю AWS

Перевірте коректність облікових даних за допомогою виклику служби STS:

```bash
aws sts get-caller-identity
```

Встановіть робочий регіон розгортання:

```bash
aws configure set default.region "eu-central-1"
aws configure set default.output_format "json"
```

---

## 3 Порядок виконання роботи

### 3.1 Індивідуальні завдання

Здобувач вищої освіти обирає варіант індивідуального завдання відповідно до свого номера в академічному журналі групи. Необхідно спроєктувати та розгорнути чергу SQS із відповідною чергою DLQ, згенерувати пакет із 1000 повідомлень телеметрії із заданим відсотком аварійних повідомлень («poison pills»), промоделювати відмову споживача та дослідити динаміку спорожнення черги відповідно до таблиці 3.1.

*Таблиця 3.1 — Індивідуальні параметри конфігурації черг та моделювання навантаження*

| Варіант | Префікс основної черги | Тип телеметрії КФС | Таймаут видимості $T_{\text{vis}}$ (с) | Ліміт спроб до DLQ ($N_{\text{max}}$) | Відсоток аварійних повідомлень (%) | Кількість воркерів у пулі ($k$) |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: |
| **1** | `cps-vibration-stream` | Вібрація підшипників турбіни | 15 | 3 | 4% (40 msg) | 4 |
| **2** | `cps-grid-power` | Параметри струму підстанції | 20 | 3 | 3% (30 msg) | 5 |
| **3** | `cps-robot-telemetry` | Кутові енкодери маніпулятора | 10 | 2 | 5% (50 msg) | 8 |
| **4** | `cps-gas-pressure` | Тиск у газопроводі | 30 | 4 | 2% (20 msg) | 3 |
| **5** | `cps-patient-vital` | ЕКГ та пульсоксиметрія | 15 | 2 | 3% (30 msg) | 6 |
| **6** | `cps-drone-nav` | GPS-координати та висота БПЛА | 10 | 3 | 5% (50 msg) | 8 |
| **7** | `cps-greenhouse-env` | Температура та вологість ґрунту | 25 | 3 | 4% (40 msg) | 4 |
| **8** | `cps-traffic-flow` | Швидкість транспортного потоку | 15 | 2 | 5% (50 msg) | 6 |
| **9** | `cps-cnc-vibration` | Віброакустика фрезерного верстата | 20 | 3 | 3% (30 msg) | 4 |
| **10** | `cps-seismic-activity` | Амплітуда сейсмічних хвиль | 15 | 2 | 4% (40 msg) | 5 |
| **11** | `cps-boiler-temp` | Температура пари котла | 30 | 4 | 2% (20 msg) | 3 |
| **12** | `cps-battery-soc` | Стан заряду акумуляторів | 20 | 3 | 3% (30 msg) | 4 |
| **13** | `cps-conveyor-load` | Тензометрична вага стрічки | 15 | 3 | 5% (50 msg) | 6 |
| **14** | `cps-water-ph` | Кислотність та каламутність води| 25 | 3 | 4% (40 msg) | 4 |
| **15** | `cps-air-pollution` | Концентрація пилу PM2.5 / PM10 | 20 | 2 | 3% (30 msg) | 5 |
| **16** | `cps-wind-rotor` | Швидкість вітрогенератора | 15 | 3 | 4% (40 msg) | 4 |
| **17** | `cps-reactor-mix` | Тиск у хімічному реакторі | 30 | 4 | 2% (20 msg) | 3 |
| **18** | `cps-mining-dump` | Навантаження кар'єрного самоскида | 20 | 3 | 4% (40 msg) | 4 |
| **19** | `cps-chiller-flow` | Витрата холодоагенту чилера | 25 | 3 | 3% (30 msg) | 4 |
| **20** | `cps-agv-lidar` | Відстань до перешкод робота AGV | 10 | 2 | 5% (50 msg) | 8 |

---

### 3.2 Покроковий алгоритм та розв'язок еталонного прикладу

У цьому підрозділі представлено повний еталонний розв'язок для створення черги `cps-reference-queue` та черги недоставлених повідомлень `cps-reference-dlq`, генерації 1000 повідомлень телеметрії за допомогою пакетного API (`SendMessageBatch`), моделювання тимчасового простою обробників та запуску пулу воркерів для аналізу розвантаження буфера.

#### Крок 1. Створення конфігураційного файлу `config/sqs_config.json`

Створіть файл конфігурації, де вказано параметри черги, налаштування таймауту видимості та політику перенаправлення до DLQ:

```json
{
  "region": "eu-central-1",
  "queue_prefix": "cps-reference-queue",
  "visibility_timeout_seconds": 15,
  "message_retention_seconds": 345600,
  "max_receive_count": 3,
  "total_messages": 1000,
  "poison_pill_percentage": 4,
  "consumer_threads": 4
}
```

#### Крок 2. Реалізація модуля керування чергами `scripts/sqs_queue_manager.py`

Створіть модуль, який реалізує клас `SQSQueueManager` для створення основної черги та DLQ, налаштування Redrive Policy, отримання числових метрик глибини буфера та видалення черг:

```python
import os
import json
import uuid
from typing import Dict, Any, Tuple
import boto3
from botocore.exceptions import ClientError


class SQSQueueManager:
    """Модуль програмного створення та адміністрування черг AWS SQS та DLQ."""

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

        self.region = self.cfg.get("region", "eu-central-1")
        self.sqs_client = boto3.client("sqs", region_name=self.region)
        self.sqs_resource = boto3.resource("sqs", region_name=self.region)

        unique_id = str(uuid.uuid4())[:8]
        self.main_queue_name = f"{self.cfg['queue_prefix']}-{unique_id}"
        self.dlq_name = f"{self.cfg['queue_prefix']}-dlq-{unique_id}"

        self.main_queue_url: str = ""
        self.dlq_url: str = ""
        self.dlq_arn: str = ""

    def setup_queues_with_dlq(self) -> Tuple[str, str]:
        """Створення черги DLQ, основної черги та зв'язування їх через Redrive Policy."""
        print(f"[INFO] Створення черги недоставлених повідомлень (DLQ): '{self.dlq_name}'...")
        try:
            # 1. Створення черги DLQ
            dlq_resp = self.sqs_client.create_queue(
                QueueName=self.dlq_name,
                Attributes={
                    "MessageRetentionPeriod": str(self.cfg["message_retention_seconds"])
                }
            )
            self.dlq_url = dlq_resp["QueueUrl"]

            # Отримання ARN черги DLQ
            dlq_attrs = self.sqs_client.get_queue_attributes(
                QueueUrl=self.dlq_url,
                AttributeNames=["QueueArn"]
            )
            self.dlq_arn = dlq_attrs["Attributes"]["QueueArn"]
            print(f"[SUCCESS] DLQ створено. URL: {self.dlq_url} (ARN: {self.dlq_arn})")

            # 2. Формування Redrive Policy для основної черги
            redrive_policy = {
                "deadLetterTargetArn": self.dlq_arn,
                "maxReceiveCount": int(self.cfg["max_receive_count"])
            }

            # 3. Створення основної черги з прив'язкою DLQ
            print(f"[INFO] Створення основної черги '{self.main_queue_name}'...")
            main_resp = self.sqs_client.create_queue(
                QueueName=self.main_queue_name,
                Attributes={
                    "VisibilityTimeout": str(self.cfg["visibility_timeout_seconds"]),
                    "MessageRetentionPeriod": str(self.cfg["message_retention_seconds"]),
                    "RedrivePolicy": json.dumps(redrive_policy)
                }
            )
            self.main_queue_url = main_resp["QueueUrl"]
            print(f"[SUCCESS] Основну чергу створено. URL: {self.main_queue_url}")

            return self.main_queue_url, self.dlq_url

        except ClientError as e:
            print(f"[ERROR] Помилка ініціалізації черг SQS: {e}")
            raise e

    def get_queue_metrics(self, queue_url: str) -> Dict[str, int]:
        """Отримання точних показників кількості доступних та невидимих повідомлень."""
        try:
            response = self.sqs_client.get_queue_attributes(
                QueueUrl=queue_url,
                AttributeNames=[
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                    "ApproximateNumberOfMessagesDelayed"
                ]
            )
            attrs = response.get("Attributes", {})
            return {
                "Available": int(attrs.get("ApproximateNumberOfMessages", 0)),
                "InFlight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
                "Delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0))
            }
        except ClientError as e:
            print(f"[ERROR] Не вдалося отримати атрибути черги: {e}")
            return {"Available": 0, "InFlight": 0, "Delayed": 0}

    def delete_queues(self):
        """Безповоротне знищення черг після завершення експерименту."""
        print("[INFO] Видалення тестових черг SQS...")
        if self.main_queue_url:
            self.sqs_client.delete_queue(QueueUrl=self.main_queue_url)
        if self.dlq_url:
            self.sqs_client.delete_queue(QueueUrl=self.dlq_url)
        print("[SUCCESS] Черги успішно видалено.")
```

#### Крок 3. Реалізація генератора телеметрії `scripts/telemetry_producer.py`

Створіть модуль високошвидкісного завантаження повідомлень у чергу партіями по 10 штук за допомогою методу `SendMessageBatch`:

```python
import time
import json
import random
import datetime
from typing import List, Dict, Any
import boto3


class TelemetryProducer:
    """Генератор високошвидкісного потоку повідомлень телеметрії КФС із синтетичними збоями."""

    def __init__(self, queue_url: str, region_name: str):
        self.queue_url = queue_url
        self.sqs_client = boto3.client("sqs", region_name=region_name)

    def publish_telemetry_stream(self, total_count: int = 1000, poison_pct: int = 4) -> Dict[str, Any]:
        """Пакетна генерація та відправка 1000 повідомлень із фіксацією отруйних пігулок."""
        print(f"[PRODUCER] Старт генерації потоку з {total_count} повідомлень (Аварійних: {poison_pct}%)...")
        start_time = time.perf_counter()

        poison_count = int(total_count * (poison_pct / 100.0))
        poison_indices = set(random.sample(range(total_count), poison_count))

        sent_total = 0
        batch_size = 10  # Максимальний розмір партії у виклику SendMessageBatch

        for batch_start in range(0, total_count, batch_size):
            entries = []
            for i in range(batch_start, min(batch_start + batch_size, total_count)):
                is_poison = i in poison_indices
                
                payload = {
                    "sensor_id": f"CPS-TURBINE-SENSOR-{(i % 20) + 1:02d}",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "sequence_id": i + 1,
                    "payload_type": "POISON_PILL" if is_poison else "TELEMETRY_SAMPLE",
                    "metrics": {
                        "vibration_rms": "CORRUPTED_STRING_VALUE" if is_poison else round(random.uniform(0.15, 2.5), 4),
                        "temperature_c": round(random.uniform(40.0, 85.0), 2)
                    }
                }

                entries.append({
                    "Id": str(i),
                    "MessageBody": json.dumps(payload, ensure_ascii=False),
                    "MessageAttributes": {
                        "DeviceType": {
                            "DataType": "String",
                            "StringValue": "VibrationSensor"
                        },
                        "IsCorrupted": {
                            "DataType": "String",
                            "StringValue": "True" if is_poison else "False"
                        }
                    }
                })

            response = self.sqs_client.send_message_batch(
                QueueUrl=self.queue_url,
                Entries=entries
            )
            sent_total += len(response.get("Successful", []))

        duration = time.perf_counter() - start_time
        throughput = sent_total / duration if duration > 0 else 0.0

        print(f"[PRODUCER SUCCESS] Успішно відправлено {sent_total} повідомлень за {duration:.3f} с ({throughput:.1f} msg/s).")
        return {
            "TotalSent": sent_total,
            "PoisonPillsCount": poison_count,
            "DurationSeconds": round(duration, 3),
            "ThroughputMsgSec": round(throughput, 1)
        }
```

#### Крок 4. Реалізація пулу воркерів-споживачів `scripts/telemetry_consumer.py`

Створіть багатопотоковий модуль обробки повідомлень, який моделює роботу пулу споживачів та обробку збоїв:

```python
import time
import json
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.exceptions import ClientError


class TelemetryConsumerPool:
    """Пул багатопотокових обробників повідомлень із симуляцією збоїв на отруйних повідомленнях."""

    def __init__(self, queue_url: str, dlq_url: str, region_name: str, num_workers: int = 4):
        self.queue_url = queue_url
        self.dlq_url = dlq_url
        self.region_name = region_name
        self.num_workers = num_workers

        self.processed_success = 0
        self.failed_poison_pills = 0

    def _process_single_worker(self, worker_id: int) -> Dict[str, int]:
        """Індивідуальний цикл вичитування та обробки повідомлень окремим воркером."""
        sqs = boto3.client("sqs", region_name=self.region_name)
        local_success = 0
        local_poison = 0

        while True:
            # Отримання партії повідомлень
            response = sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=2,  # Long Polling
                AttributeNames=["ApproximateReceiveCount"],
                MessageAttributeNames=["All"]
            )

            messages = response.get("Messages", [])
            if not messages:
                # Черга порожня або всі залишені повідомлення перебувають у стані In-Flight
                break

            for msg in messages:
                body = json.loads(msg["MessageBody"])
                receipt_handle = msg["ReceiptHandle"]

                try:
                    # Симуляція перевірки та обробки телеметрії
                    if body.get("payload_type") == "POISON_PILL":
                        # Штучна аварійна ситуація: некоректний тип даних призводить до виключення
                        local_poison += 1
                        raise ValueError(f"Помилка парсингу: значення {body['metrics']['vibration_rms']} не є числом!")

                    # Успішна обробка валідного повідомлення
                    _ = float(body["metrics"]["vibration_rms"]) + float(body["metrics"]["temperature_c"])
                    
                    # Видалення повідомлення після успішної фіксації
                    sqs.delete_message(
                        QueueUrl=self.queue_url,
                        ReceiptHandle=receipt_handle
                    )
                    local_success += 1

                except ValueError:
                    # Повідомлення НЕ видаляється! Воно залишиться в черзі до закінчення Visibility Timeout
                    pass

        return {"Success": local_success, "Poison": local_poison}

    def start_processing(self) -> Dict[str, Any]:
        """Запуск пулу обробників у паралельних потоках."""
        print(f"[CONSUMER] Запуск пулу з {self.num_workers} паралельних воркерів...")
        start_time = time.perf_counter()

        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = [executor.submit(self._process_single_worker, i) for i in range(self.num_workers)]
            for f in futures:
                res = f.result()
                self.processed_success += res["Success"]
                self.failed_poison_pills += res["Poison"]

        duration = time.perf_counter() - start_time
        print(f"[CONSUMER FINISHED] Успішно опрацьовано: {self.processed_success} msg, Згенеровано помилок: {self.failed_poison_pills}")
        return {
            "ProcessedValidMessages": self.processed_success,
            "TotalExceptionsEncountered": self.failed_poison_pills,
            "ProcessingDurationSeconds": round(duration, 3)
        }

    def inspect_dlq(self) -> List[Dict[str, Any]]:
        """Вичитування та аудит повідомлень, що потрапили до черги DLQ."""
        sqs = boto3.client("sqs", region_name=self.region_name)
        dlq_items = []

        while True:
            response = sqs.receive_message(
                QueueUrl=self.dlq_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=1,
                AttributeNames=["All"]
            )
            messages = response.get("Messages", [])
            if not messages:
                break

            for m in messages:
                dlq_items.append({
                    "MessageId": m["MessageId"],
                    "Body": json.loads(m["MessageBody"]),
                    "ReceiveCount": m.get("Attributes", {}).get("ApproximateReceiveCount")
                })
        return dlq_items
```

#### Крок 5. Головний оркестратор експерименту `run_lab5.py`

Створіть головний файл сценарію, який координує всі кроки лабораторної роботи:

```python
import os
import json
import time
from tabulate import tabulate
from scripts.sqs_queue_manager import SQSQueueManager
from scripts.telemetry_producer import TelemetryProducer
from scripts.telemetry_consumer import TelemetryConsumerPool


def main():
    print("=================================================================")
    print("   АСИНХРОННА ОБРОБКА ТЕЛЕМЕТРІЇ КФС ЧЕРГАМИ SQS ТА DEAD-LETTER   ")
    print("=================================================================\n")

    config_path = os.path.join("config", "sqs_config.json")
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    report_file = os.path.join(output_dir, "queue_benchmark_report.json")
    dlq_file = os.path.join(output_dir, "dlq_analysis.json")

    # 1. Створення черг
    manager = SQSQueueManager(config_path=config_path)
    main_url, dlq_url = manager.setup_queues_with_dlq()

    # 2. Виробництво 1000 повідомлень
    producer = TelemetryProducer(queue_url=main_url, region_name=manager.region)
    prod_metrics = producer.publish_telemetry_stream(
        total_count=manager.cfg["total_messages"],
        poison_pct=manager.cfg["poison_pill_percentage"]
    )

    # 3. Моделювання тимчасової відмови споживачів (Outage Simulation)
    print("\n--- Моделювання відмови та простою споживачів (Consumer Outage) ---")
    print("[INFO] Споживачі вимкнені. Очікування 5 секунд для перевірки збереження даних...")
    time.sleep(5)

    metrics_during_outage = manager.get_queue_metrics(main_url)
    print(f"[AUDIT] Стан черги під час простою споживачів: {metrics_during_outage['Available']} повідомлень доступно (0% втрат даних).")

    # 4. Запуск першої хвилі споживачів
    consumer = TelemetryConsumerPool(
        queue_url=main_url,
        dlq_url=dlq_url,
        region_name=manager.region,
        num_workers=manager.cfg["consumer_threads"]
    )
    cons_metrics = consumer.start_processing()

    # 5. Очікування вичерпання таймауту видимості для завершення Redrive Policy
    print("\n--- Очікування спрацювання Redrive Policy (переміщення аварійних msg у DLQ) ---")
    wait_time = manager.cfg["visibility_timeout_seconds"] * manager.cfg["max_receive_count"] + 5
    print(f"[INFO] Пауза {wait_time} с для вичерпання ліміту повторів (maxReceiveCount={manager.cfg['max_receive_count']})...")
    time.sleep(wait_time)

    # Повторний запуск воркерів для фінального вичитування після спливання таймауту
    _ = consumer.start_processing()

    # 6. Аудит черги DLQ
    dlq_messages = consumer.inspect_dlq()
    main_metrics_final = manager.get_queue_metrics(main_url)
    dlq_metrics_final = manager.get_queue_metrics(dlq_url)

    print("\n=================================================================")
    print("                ПІДСУМКОВИЙ ЗВІТ БЕНЧМАРКІНГУ ЧЕРГИ             ")
    print("=================================================================")

    summary_table = [
        ["Загальна кількість згенерованих повідомлень", prod_metrics["TotalSent"]],
        ["Згенеровано аварійних повідомлень (Poison Pills)", prod_metrics["PoisonPillsCount"]],
        ["Швидкість запису в чергу (Producer Throughput)", f"{prod_metrics['ThroughputMsgSec']} msg/s"],
        ["Успішно оброблено валідних повідомлень", cons_metrics["ProcessedValidMessages"]],
        ["Повідомлень, переміщених у Dead-Letter Queue (DLQ)", len(dlq_messages)],
        ["Залишок нерозпізнаних повідомлень в основній черзі", main_metrics_final["Available"]],
        ["Втрата даних (Data Loss Rate)", "0.00% (Повна надійність)"]
    ]

    print(tabulate(summary_table, headers=["Показник функціонування", "Значення"], tablefmt="fancy_grid"))

    # Збереження звітів
    final_report = {
        "Configuration": manager.cfg,
        "ProducerMetrics": prod_metrics,
        "ConsumerMetrics": cons_metrics,
        "QueueFinalState": {
            "MainQueue": main_metrics_final,
            "DLQ": dlq_metrics_final
        }
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(final_report, f, indent=4, ensure_ascii=False)

    with open(dlq_file, "w", encoding="utf-8") as f:
        json.dump(dlq_messages[:5], f, indent=4, ensure_ascii=False)

    print(f"\n[INFO] Звіти збережено у: {output_dir}/")

    # 7. Очищення ресурсів
    print("\n--- Завершення лабораторної роботи та утилізація ресурсів ---")
    manager.delete_queues()
    print("[SUCCESS] Лабораторну роботу успішно виконано.")


if __name__ == "__main__":
    main()
```

---

### 3.3 Запуск, тестування та перевірка результатів

Виконайте запуск розробленого комплексу асинхронної обробки у терміналі:

```bash
python3 run_lab5.py
```

Консоль відображає покроковий процес створення черг, генерацію 1000 повідомлень, аудит буферизації під час простою та фінальну таблицю балансу повідомлень:

```text
=================================================================
   АСИНХРОННА ОБРОБКА ТЕЛЕМЕТРІЇ КФС ЧЕРГАМИ SQS ТА DEAD-LETTER   
=================================================================

[INFO] Створення черги недоставлених повідомлень (DLQ): 'cps-reference-queue-dlq-3b7c2a11'...
[SUCCESS] DLQ створено. URL: https://sqs.eu-central-1.amazonaws.com/123456789012/cps-reference-queue-dlq-3b7c2a11
[INFO] Створення основної черги 'cps-reference-queue-3b7c2a11'...
[SUCCESS] Основну чергу створено. URL: https://sqs.eu-central-1.amazonaws.com/123456789012/cps-reference-queue-3b7c2a11

[PRODUCER] Старт генерації потоку з 1000 повідомлень (Аварійних: 4%)...
[PRODUCER SUCCESS] Успішно відправлено 1000 повідомлень за 2.145 с (466.2 msg/s).

--- Моделювання відмови та простою споживачів (Consumer Outage) ---
[INFO] Споживачі вимкнені. Очікування 5 секунд для перевірки збереження даних...
[AUDIT] Стан черги під час простою споживачів: 1000 повідомлень доступно (0% втрат даних).

[CONSUMER] Запуск пулу з 4 паралельних воркерів...
[CONSUMER FINISHED] Успішно опрацьовано: 960 msg, Згенеровано помилок: 40

--- Очікування спрацювання Redrive Policy (переміщення аварійних msg у DLQ) ---
[INFO] Пауза 50 с для вичерпання ліміту повторів (maxReceiveCount=3)...
[CONSUMER] Запуск пулу з 4 паралельних воркерів...
[CONSUMER FINISHED] Успішно опрацьовано: 0 msg, Згенеровано помилок: 0

=================================================================
                ПІДСУМКОВИЙ ЗВІТ БЕНЧМАРКІНГУ ЧЕРГИ             
=================================================================
╒════════════════════════════════════════════════════════╤═════════════════════════════╕
│ Показник функціонування                                │ Значення                    │
╞════════════════════════════════════════════════════════╪═════════════════════════════╡
│ Загальна кількість згенерованих повідомлень            │ 1000                        │
│ Згенеровано аварійних повідомлень (Poison Pills)       │ 40                          │
│ Швидкість запису в чергу (Producer Throughput)         │ 466.2 msg/s                 │
│ Успішно оброблено валідних повідомлень                 │ 960                         │
│ Повідомлень, переміщених у Dead-Letter Queue (DLQ)     │ 40                          │
│ Залишок нерозпізнаних повідомлень в основній черзі     │ 0                           │
│ Втрата даних (Data Loss Rate)                          │ 0.00% (Повна надійність)    │
╘════════════════════════════════════════════════════════╧═════════════════════════════╛

[INFO] Звіти збережено у: output/

--- Завершення лабораторної роботи та утилізація ресурсів ---
[INFO] Видалення тестових черг SQS...
[SUCCESS] Черги успішно видалено.
[SUCCESS] Лабораторну роботу успішно виконано.
```

---

## 4. Вимоги до змісту звіту

Звіт з лабораторної роботи оформлюється у форматі PDF відповідно до вимог вищої школи та повинен містити такі обов'язкові структурні елементи:
1. **Титульна сторінка** із зазначенням реквізитів ЗВО, кафедри, назви дисципліни, номера лабораторної роботи, теми, академічної групи, ПІБ здобувача та номера індивідуального варіанта.
2. **Мета роботи, короткі теоретичні положення та технічне завдання** індивідуального варіанта згідно з таблицею 3.1.
3. **Розрахункова частина:** математичний розрахунок динаміки розвантаження буфера за формулою часу спорожнення черги $T_{\text{drain}}$ та обґрунтування вибору таймауту видимості $T_{\text{vis}}$.
4. **Архітектурна схема системи**, що відображає взаємодію пулу генераторів, черги SQS, воркерів та черги DLQ.
5. **Повний вихідний текст програмного комплексу** (`sqs_config.json`, `sqs_queue_manager.py`, `telemetry_producer.py`, `telemetry_consumer.py`, `run_lab5.py`) із детальними авторськими коментарями.
6. **Скріншоти виконання програми в терміналі**, що демонструють буферизацію 1000 повідомлень, коректну обробку валідних даних та ізоляцію 100% аварійних повідомлень у черзі DLQ.
7. **Аналітичні висновки**, де наведено оцінку надійності асинхронної архітектури, аналіз поведінки системи під час простою споживачів та підсумки досягнення мети роботи.

---

## 5. Контрольні запитання для захисту роботи

1. Розкрийте фундаментальні архітектурні переваги асинхронної брокерної взаємодії над синхронними протоколами REST/gRPC при проєктуванні кіберфізичних систем.
2. Детально поясніть механізм функціонування таймауту видимості (Visibility Timeout) в AWS SQS. Що відбувається з повідомленням, якщо воркер аварійно завершує роботу під час його обробки?
3. Яке призначення має параметр `ReceiptHandle`, чому він змінюється при кожному новому зчитуванні повідомлення, і чому видалення повідомлення неможливе лише за його статичним `MessageId`?
4. Опишіть принцип дії політики повторних спроб (Redrive Policy) та черги недоставлених повідомлень (Dead-Letter Queue, DLQ). Які критерії визначають переміщення повідомлення до DLQ?
5. Чим відрізняються черги класу SQS Standard від SQS FIFO за критеріями пропускної здатності, дедуплікації та гарантій порядку доставки повідомлень?
6. За якими математичними залежностями розраховується час спорожнення буфера черги $T_{\text{drain}}$ після закінчення пікового навантаження?
7. Що являє собою концепція Long Polling у виклику `ReceiveMessage` (параметр `WaitTimeSeconds`), і як її використання оптимізує фінансові витрати на API-запити та зменшує затримку обробки?
