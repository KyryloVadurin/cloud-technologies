# Лабораторна робота № 1. Програмне керування та автоматизація життєвого циклу інстансів IaaS засобами Cloud CLI та Python SDK

**Мета:** Дослідження фундаментальних архітектурних принципів обчислювальних ресурсів класу «Інфраструктура як послуга» (IaaS), здобуття практичних навичок конфігурування хмарних інтерфейсів командного рядка (Cloud CLI), опанування методів програмної автентифікації та розробка комплексних сценаріїв автоматизації повного життєвого циклу віртуальних машин (створення, параметризація, моніторинг станів, модифікація конфігурації та безпечна утилізація) мовою Python з використанням бібліотеки Boto3 в інфраструктурі Amazon Web Services.

**Стек технологій та інструменти:**
* **Мова програмування та середовище:** Python 3.10+ (CPython), віртуальне середовище `venv`.
* **Платформа та бібліотеки:** Хмарна платформа Amazon Web Services (AWS), бібліотеки `boto3` (v1.34+), `botocore` (v1.34+), `tabulate` (v0.9+), емулятор локальної хмари `LocalStack` (опціонально для офлайн-тестування).
* **Інструменти розробки:** Інтерфейс командного рядка AWS CLI v2, інтегроване середовище розробки Visual Studio Code / PyCharm, система контролю версій Git, емулятор терміналу Bash / PowerShell.

---

## 1 Теоретичні відомості

Обчислювальні ресурси моделі «Інфраструктура як послуга» (**IaaS**) є базовим будівельним блоком сучасних хмарних систем. В екосистемі Amazon Web Services сервіс віртуальних обчислень представлений платформою **Amazon Elastic Compute Cloud (AWS EC2)**. Віртуальний сервер у термінології хмарних обчислень іменується **інстансом (Instance)**. Інстанс функціонує як повністю ізольована віртуальна машина, що виконується під управлінням апаратного гіпервізора (KVM або Nitro Hypervisor) на фізичних серверах провайдера.

Архітектура інстансу EC2 базується на трьох взаємопов'язаних компонентах:
1. **Базовий образ віртуальної машини (Amazon Machine Image, AMI).** Шаблон, який містить попередньо встановлену та налаштовану операційну систему (Linux, Windows Server), системні бібліотеки, драйвери паралельного вводу/виводу (VirtIO / ENA) та початкову конфігурацію ініціалізації.
2. **Тип та розмір інстансу (Instance Type).** Апаратно-віртуальна специфікація, яка визначає кількість виділених віртуальних ядер процесора (**vCPU**), обсяг оперативної пам'яті (**RAM**), гарантовану смугу пропускання дискового підключення до сховища EBS (**EBS Bandwidth**) та продуктивність мережевого адаптера (**Network Performance**). Класифікація інстансів використовує стандартизовану номенклатуру, де літера позначає сімейство (наприклад, `t` — інстанси зі змінною продуктивністю, `c` — оптимізовані для обчислень, `m` — загального призначення), цифра — покоління мікроархітектури, а суфікс після крапки — розмірний коефіцієнт (наприклад, `t3.micro`, `c5.large`).
3. **Блокові накопичувачі (Root & Data Volumes).** Віртуалізовані блокові пристрої **Amazon Elastic Block Store (EBS)**, які виконують роль системного завантажувального або додаткового диска даних.

Життєвий цикл інстансу EC2 підпорядковується детермінованому скінченному автомату станів. Після відправки команди створення віртуальна машина переходить у стан ініціалізації `pending`, під час якого гіпервізор виділяє фізичні ресурси на хості та монтує системний том EBS. Після успішного старту ядра ОС інстанс переходить у стан `running`. 

У цьому стані обчислювальний вузол споживає ресурси процесора і тарифікується за посекундною моделлю. За командою користувача інстанс може бути зупинений (`stopping` $\to$ `stopped`), під час чого оперативна пам'ять звільняється, а стан кореневого диска зберігається в EBS без нарахування плати за процесорний час. Повне видалення інстансу з інфраструктури переводить його у стан `shutting-down` та фінальний стан `terminated`, після чого всі асоційовані ресурси безповоротно вивільняються.

```mermaid
stateDiagram-v2
    [*] --> pending: Запит run_instances()
    pending --> running: Успішна алокація та бут ОС
    
    running --> stopping: Запит stop_instances()
    stopping --> stopped: Пам'ять звільнено, диск EBS збережено
    
    stopped --> pending: Запит start_instances()
    stopped --> shutting_down: Запит terminate_instances()
    
    running --> rebooting: Запит reboot_instances()
    rebooting --> running: М'яке перезавантаження ядра
    
    running --> shutting_down: Запит terminate_instances()
    shutting_down --> terminated: Повне знищення ресурсів
    terminated --> [*]
```
*Рисунок 1.1 — Граф станів та переходи життєвого циклу інстансу AWS EC2*

Програмне керування хмарною інфраструктурою реалізується шляхом надсилання формалізованих HTTP/HTTPS-запитів до уніфікованого **AWS Query API**. Кожен запит обов'язково підписується за допомогою криптографічного протоколу **AWS Signature Version 4 (SigV4)** із використанням хеш-функції SHA-256 на основі пари ключів доступу: відкритого ідентифікатора (`AWS_ACCESS_KEY_ID`) та закритого ключа підпису (`AWS_SECRET_ACCESS_KEY`).

Для мови програмування Python офіційним інструментом взаємодії є бібліотека **Boto3**. Архітектура Boto3 складається з трьох рівнів абстракції:
1. **Рівень сесії (Session).** Керує станом підключення, конфігурацією регіону за замовчуванням та автентифікаційними даними користувача.
2. **Низькорівневий клієнт (Client).** Забезпечує пряме відображення 1:1 методів сервісу на виклики REST API. Методи клієнта (наприклад, `ec2_client.describe_instances()`) повертають «сирі» словники Python, що відповідають повній схемі JSON-відповіді провайдера, надаючи максимальний контроль над усіма параметрами.
3. **Високорівневий ресурс (Resource).** Об'єктно-орієнтована абстракція, яка інкапсулює стан хмарних ресурсів у сутності Python (наприклад, об'єкт класу `ec2.Instance`), дозволяючи виконувати дії безпосередньо як виклики методів об'єкта (наприклад, `instance.stop()`).

```mermaid
flowchart LR
    subgraph PythonApp ["Прикладний скрипт автоматизації"]
        Script[ec2_lifecycle_manager.py]
    end

    subgraph Boto3Layer ["Архітектура SDK Boto3"]
        Session[boto3.Session] --> Client[boto3.client 'ec2']
        Session --> Resource[boto3.resource 'ec2']
        Client --> Botocore[Botocore Engine: SigV4 Signer]
        Resource --> Client
    end

    subgraph AWSCloud ["Хмарна інфраструктура AWS"]
        APIGateway[AWS EC2 HTTPS Endpoint: ec2.eu-central-1.amazonaws.com]
        Hypervisor[Хмарний оркестратор та гіпервізори]
    end

    Script ===> Session
    Botocore ===>|HTTPS POST + SigV4 Auth| APIGateway
    APIGateway ===> Hypervisor
```
*Рисунок 1.2 — Архітектура стека програмної взаємодії Boto3 SDK із хмарним API сервісу EC2*

Критичним аспектом надійного скриптингу хмари є асинхронність операцій. Виклик API для запуску чи зупинки інстансу повертає відповідь негайно після реєстрації запиту в системі, проте фактичний перехід стану займає від кількох секунд до кількох хвилин. 

Для уникнення нестабільності застосовується механізм очікувачів (**Waiters**). Очікувач реалізує алгоритм активного опитування (**Polling**) з експоненційним або фіксованим інтервалом, блокуючи виконання скрипту до моменту переходу ресурсу у цільовий стан.

Сумарний час очікування переходу стану $T_{\text{wait}}$ математично описується рівнянням:

$$T_{\text{wait}} = \sum_{i=1}^{k} \left( \Delta t_{\text{interval}} + \tau_{\text{api}}(i) \right)$$

де $\Delta t_{\text{interval}}$ — період між послідовними опитуваннями стану (для очікувача `instance_running` становить 15 секунд), $\tau_{\text{api}}(i)$ — мережева затримка виконання $i$-го запиту опитування, $k$ — кількість ітерацій опитування до досягнення цільового стану ($1 \le k \le k_{\text{max}}$, де $k_{\text{max}} = 40$ визначає ліміт таймауту).

Сукупна вартість використання інстансів $C_{\text{total}}$ за розрахунковий період розраховується на основі формули квантування часу роботи:

$$C_{\text{total}} = \sum_{j=1}^{M} \left( \max\left(60, \, t_{\text{run}, j}\right) \cdot \frac{P_{\text{compute}}}{3600} + V_{\text{EBS}, j} \cdot P_{\text{storage}} \cdot \frac{t_{\text{life}, j}}{T_{\text{month}}} \right)$$

де $M$ — кількість запущених інстансів, $t_{\text{run}, j}$ — фактична тривалість перебування $j$-го інстансу в стані `running` (у секундах, із мінімальним тарифікаційним квантом 60 секунд), $P_{\text{compute}}$ — годинний тариф обраного типу інстансу (у доларах США за годину), $V_{\text{EBS}, j}$ — виділений обсяг блокового сховища EBS (у гігабайтах), $P_{\text{storage}}$ — місячний тариф за 1 ГБ сховища, $t_{\text{life}, j}$ — повний час існування дискового тому від моменту виділення до знищення, $T_{\text{month}}$ — тривалість розрахункового місяця в секундах ($2{,}592 \cdot 10^6$ с).

---

## 2 Підготовка середовища та розгортання проєкту (Крок 0)

Для виконання лабораторної роботи здобувач вищої освіти повинен налаштувати локальне робоче середовище, встановити інтерпретатор мови Python, комплект утиліт AWS CLI, створити ізольоване віртуальне оточення та встановити необхідні бібліотеки.

### 2.1 Перевірка та встановлення базових утиліт

Відкрийте термінал операційної системи та виконайте перевірку наявності інтерпретатора Python версії 3.10 або вище та системи керування пакетами pip:

```bash
python3 --version
pip3 --version
```

У разі відсутності інтерфейсу командного рядка AWS CLI v2 виконайте його завантаження та інсталяцію (для ОС Linux Ubuntu / Debian):

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
aws --version
```

### 2.2 Структура каталогів проєкту

Створіть робочу директорію проєкту та ініціалізуйте віртуальне середовище Python:

```bash
mkdir -p ~/cloud_labs/lab1_ec2_lifecycle
cd ~/cloud_labs/lab1_ec2_lifecycle
python3 -m venv venv
source venv/bin/activate
```

Сформуйте файлову структуру проєкту відповідно до наведеної схеми:

```text
lab1_ec2_lifecycle/
├── config/
│   └── settings.json          # Конфігураційний файл параметрів варіанта
├── scripts/
│   ├── __init__.py
│   ├── ec2_manager.py         # Основний модуль програмного керування Boto3
│   └── user_data.sh           # Shell-скрипт ініціалізації вузла (cloud-init)
├── output/
│   └── instance_manifest.json # Автоматично згенерований звіт параметрів ВМ
├── requirements.txt           # Специфікація залежностей проєкту
└── main.py                    # Головна точка входу для запуску сценарію
```

Створіть файл специфікації залежностей `requirements.txt`:

```text
boto3>=1.34.0
botocore>=1.34.0
tabulate>=0.9.0
```

Встановіть залежності у віртуальне середовище:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 2.3 Конфігурування облікових даних доступу

Для автентифікації запитів до AWS виконайте налаштування конфігураційного профілю за допомогою команди `aws configure`. Якщо робота виконується в навчальній пісочниці (AWS Academy / Sandbox), введіть надані викладачем тимчасові креденшали. Якщо використовується локальний емулятор `LocalStack`, введіть тестові значення:

```bash
aws configure set aws_access_key_id "AKIAIOSFODNN7EXAMPLE"
aws configure set aws_secret_access_key "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
aws configure set default.region "eu-central-1"
aws configure set default.output_format "json"
```

Перевірте коректність налаштування та доступність API:

```bash
aws sts get-caller-identity
```

---

## 3 Порядок виконання роботи

### 3.1 Індивідуальні завдання

Здобувач вищої освіти обирає варіант індивідуального завдання відповідно до свого порядкового номера у журналі академічної групи. Необхідно реалізувати програмний комплекс, який створює, конфігурує, тестує та утилізує інстанс згідно з параметрами, наведеними в таблиці 3.1.

*Таблиця 3.1 — Матриця індивідуальних завдань лабораторної роботи*

| Варіант | Назва цільового вузла КФС | Тип інстансу | Базовий образ ОС (AMI) | Обсяг EBS (ГБ) | Специфікація ініціалізаційного сценарію User Data |
| :---: | :--- | :--- | :--- | :---: | :--- |
| **1** | `cps-telemetry-collector` | `t3.nano` | Ubuntu 22.04 LTS | 10 | Встановлення Python 3, запуск HTTP-демона телеметрії на порту 8080 |
| **2** | `cps-edge-gateway` | `t3.micro` | Amazon Linux 2023 | 12 | Встановлення Nginx, налаштування reverse-proxy для брокера повідомлень |
| **3** | `cps-sensor-aggregator` | `t3.micro` | Debian 12 | 15 | Встановлення Mosquitto MQTT Broker, відкриття порту 1883 для сенсорів |
| **4** | `cps-actuator-controller` | `t3.small` | Ubuntu 22.04 LTS | 20 | Встановлення Docker CE, запуск контейнера емулятора сервоприводів |
| **5** | `cps-edge-analytics` | `t3.small` | Amazon Linux 2023 | 15 | Встановлення Redis Server, конфігурування in-memory буфера вимірювань |
| **6** | `cps-video-ingest` | `t3.medium` | Ubuntu 22.04 LTS | 25 | Встановлення FFmpeg, запуск демона обробки потокового RTSP відео |
| **7** | `cps-signal-filter` | `t3.nano` | Debian 12 | 10 | Встановлення Python 3, NumPy, запуск скрипту цифрової фільтрації сигналу |
| **8** | `cps-modbus-bridge` | `t3.micro` | Amazon Linux 2023 | 12 | Встановлення середовища Node.js, запуск шлюзу Modbus TCP/IP |
| **9** | `cps-scada-node` | `t3.medium` | Ubuntu 22.04 LTS | 30 | Встановлення Prometheus Node Exporter, запуск агента збору метрик |
| **10** | `cps-plc-monitor` | `t3.micro` | Debian 12 | 14 | Встановлення SQLite, запуск демона протоколювання аварійних подій |
| **11** | `cps-coap-server` | `t3.nano` | Amazon Linux 2023 | 10 | Встановлення бібліотеки aiocoap, відкриття UDP-порту 5683 для датчиків |
| **12** | `cps-timeseries-node` | `t3.small` | Ubuntu 22.04 LTS | 20 | Встановлення InfluxDB v2, ініціалізація бакета збереження телеметрії |
| **13** | `cps-security-gateway` | `t3.micro` | Debian 12 | 15 | Встановлення OpenVPN / WireGuard, генерація ключів шифрування каналу |
| **14** | `cps-data-normalizer` | `t3.small` | Amazon Linux 2023 | 16 | Встановлення Python 3, Pandas, конфігурування пайплайну валідації JSON |
| **15** | `cps-firmware-server` | `t3.micro` | Ubuntu 22.04 LTS | 18 | Встановлення вебсервера Apache HTTPD, хостинг OTA-образів прошивок |
| **16** | `cps-lora-concentrator` | `t3.nano` | Debian 12 | 10 | Встановлення LoRaWAN Packet Forwarder, відкриття UDP-портів зв'язку |
| **17** | `cps-digital-twin-core` | `t3.medium` | Ubuntu 22.04 LTS | 25 | Встановлення OpenJDK 17, запуск мікросервісу цифрового двійника КФС |
| **18** | `cps-can-bus-logger` | `t3.micro` | Amazon Linux 2023 | 12 | Встановлення утиліт can-utils, налаштування демона логування кадрів |
| **19** | `cps-ml-inference-edge` | `t3.small` | Ubuntu 22.04 LTS | 20 | Встановлення ONNX Runtime, запуск моделі класифікації аномалій |
| **20** | `cps-backup-orchestrator` | `t3.micro` | Debian 12 | 15 | Встановлення утиліти AWS CLI на інстансі, налаштування cron-бекапів |

---

### 3.2 Покроковий алгоритм та розв'язок еталонного прикладу

У даному розділі наведено повний еталонний розв'язок базового навчального варіанта зі створення обчислювального вузла `cps-reference-controller` на базі ОС Ubuntu 22.04 LTS (`t3.micro`) із автоматичною генерацією пари SSH-ключів, створенням групи безпеки, моніторингом ініціалізації через механізм Waiters та керованим життєвим циклом.

#### Крок 1. Створення конфігураційного файлу параметрів `config/settings.json`

Створіть файл конфігурації, де централізовано зберігатимуться параметри створюваного середовища:

```json
{
  "region_name": "eu-central-1",
  "instance_name": "cps-reference-controller",
  "instance_type": "t3.micro",
  "ami_id": "ami-0faab6bdbac9486fb",
  "volume_size_gb": 10,
  "key_pair_name": "cps-lab1-keypair",
  "security_group_name": "cps-lab1-secgroup",
  "tags": {
    "Project": "CyberPhysicalSystem",
    "Environment": "Laboratory",
    "ManagedBy": "Boto3-Automation",
    "Owner": "Student-Master"
  }
}
```

#### Крок 2. Створення ініціалізаційного скрипту `scripts/user_data.sh`

Створіть shell-скрипт, який буде переданий механізму `cloud-init` під час першого завантаження операційної системи віртуальної машини:

```bash
#!/bin/bash
# Оновлення індексу пакетів та встановлення необхідних сервісів
apt-get update -y
apt-get install -y python3-pip nginx htop curl jq

# Створення директорії підсистеми телеметрії
mkdir -p /opt/cps_telemetry

# Формування тестового демона моніторингу телеметрії
cat << 'EOF' > /opt/cps_telemetry/telemetry_daemon.py
import http.server
import socketserver
import json
import datetime
import os

PORT = 8080

class TelemetryHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response = {
            "node_status": "ONLINE",
            "system_time": datetime.datetime.utcnow().isoformat(),
            "telemetry_source": "CPS-Reference-Node",
            "metrics": {
                "cpu_load_percent": os.getloadavg()[0] * 100,
                "memory_available_kb": 1024 * 1024
            }
        }
        self.wfile.write(json.dumps(response).encode('utf-8'))

with socketserver.TCPServer(("", PORT), TelemetryHandler) as httpd:
    httpd.serve_forever()
EOF

# Запуск демона у фоновому режимі
nohup python3 /opt/cps_telemetry/telemetry_daemon.py > /var/log/cps_telemetry.log 2>&1 &
```

#### Крок 3. Реалізація керуючого модуля `scripts/ec2_manager.py`

Створіть основний модуль взаємодії з API AWS, який реалізує клас `EC2LifecycleManager`:

```python
import os
import time
import json
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError


class EC2LifecycleManager:
    """Клас програмного керування життєвим циклом інстансів IaaS у хмарі AWS."""

    def __init__(self, config_path: str):
        """Ініціалізація менеджера та зчитування конфігураційного маніфесту."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Конфігураційний файл не знайдено: {config_path}")
            
        with open(config_path, "r", encoding="utf-8") as file:
            self.config = json.load(file)
            
        self.region = self.config.get("region_name", "eu-central-1")
        self.session = boto3.Session(region_name=self.region)
        self.ec2_client = self.session.client("ec2")
        self.ec2_resource = self.session.resource("ec2")
        
        self.instance_id: Optional[str] = None
        self.key_pair_name = self.config.get("key_pair_name", "cps-keypair")
        self.security_group_name = self.config.get("security_group_name", "cps-secgroup")

    def ensure_key_pair(self) -> str:
        """Перевірка наявності або створення нової пари SSH-ключів."""
        try:
            response = self.ec2_client.describe_key_pairs(KeyNames=[self.key_pair_name])
            print(f"[INFO] SSH-ключ '{self.key_pair_name}' знайдено в інфраструктурі.")
            return self.key_pair_name
        except ClientError as error:
            if "InvalidKeyPair.NotFound" in str(error):
                print(f"[INFO] Генерація нового SSH-ключа '{self.key_pair_name}'...")
                key_response = self.ec2_client.create_key_pair(KeyName=self.key_pair_name)
                private_key_path = f"{self.key_pair_name}.pem"
                with open(private_key_path, "w", encoding="utf-8") as key_file:
                    key_file.write(key_response["KeyMaterial"])
                os.chmod(private_key_path, 0o400)
                print(f"[SUCCESS] Приватний ключ збережено у файл: {private_key_path}")
                return self.key_pair_name
            else:
                raise error

    def ensure_security_group(self) -> str:
        """Створення та конфігурування правил мережевого екрана (Security Group)."""
        try:
            response = self.ec2_client.describe_security_groups(
                GroupNames=[self.security_group_name]
            )
            group_id = response["SecurityGroups"][0]["GroupId"]
            print(f"[INFO] Security Group '{self.security_group_name}' знайдено (ID: {group_id}).")
            return group_id
        except ClientError as error:
            if "InvalidGroup.NotFound" in str(error):
                print(f"[INFO] Створення Security Group '{self.security_group_name}'...")
                vpc_response = self.ec2_client.describe_vpcs(
                    Filters=[{"Name": "isDefault", "Values": ["true"]}]
                )
                default_vpc_id = vpc_response["Vpcs"][0]["VpcId"]
                
                group_response = self.ec2_client.create_security_group(
                    GroupName=self.security_group_name,
                    Description="Security Group for CPS Telemetry and Management",
                    VpcId=default_vpc_id
                )
                group_id = group_response["GroupId"]
                
                # Додавання правил фільтрації трафіку Ingress
                self.ec2_client.authorize_security_group_ingress(
                    GroupId=group_id,
                    IpPermissions=[
                        {
                            "IpProtocol": "tcp",
                            "FromPort": 22,
                            "ToPort": 22,
                            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "SSH Access"}]
                        },
                        {
                            "IpProtocol": "tcp",
                            "FromPort": 80,
                            "ToPort": 80,
                            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "HTTP Web"}]
                        },
                        {
                            "IpProtocol": "tcp",
                            "FromPort": 8080,
                            "ToPort": 8080,
                            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "CPS Telemetry API"}]
                        }
                    ]
                )
                print(f"[SUCCESS] Security Group успішно створено з відкритими портами 22, 80, 8080.")
                return group_id
            else:
                raise error

    def provision_instance(self, user_data_script_path: str) -> Dict[str, Any]:
        """Створення та запуск віртуальної машини згідно з конфігурацією."""
        key_name = self.ensure_key_pair()
        group_id = self.ensure_security_group()
        
        user_data_content = ""
        if os.path.exists(user_data_script_path):
            with open(user_data_script_path, "r", encoding="utf-8") as script_file:
                user_data_content = script_file.read()

        tag_specifications = [
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name", "Value": self.config.get("instance_name", "cps-node")}
                ] + [
                    {"Key": k, "Value": v} for k, v in self.config.get("tags", {}).items()
                ]
            }
        ]

        block_device_mappings = [
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": self.config.get("volume_size_gb", 10),
                    "VolumeType": "gp3",
                    "DeleteOnTermination": True
                }
            }
        ]

        print(f"[INFO] Запуск процедури створення інстансу типу '{self.config['instance_type']}'...")
        response = self.ec2_client.run_instances(
            ImageId=self.config["ami_id"],
            InstanceType=self.config["instance_type"],
            KeyName=key_name,
            SecurityGroupIds=[group_id],
            MinCount=1,
            MaxCount=1,
            UserData=user_data_content,
            BlockDeviceMappings=block_device_mappings,
            TagSpecifications=tag_specifications
        )

        self.instance_id = response["Instances"][0]["InstanceId"]
        print(f"[SUCCESS] Запит прийнято. Створено інстанс з ідентифікатором: {self.instance_id}")
        return response["Instances"][0]

    def wait_for_state(self, target_state: str = "running", max_attempts: int = 40):
        """Очікування переходу інстансу в цільовий стан за допомогою механізму Waiters."""
        if not self.instance_id:
            raise ValueError("Ідентифікатор інстансу не визначено.")
            
        print(f"[INFO] Очікування переходу інстансу {self.instance_id} у стан '{target_state}'...")
        if target_state == "running":
            waiter = self.ec2_client.get_waiter("instance_running")
        elif target_state == "stopped":
            waiter = self.ec2_client.get_waiter("instance_stopped")
        elif target_state == "terminated":
            waiter = self.ec2_client.get_waiter("instance_terminated")
        else:
            raise ValueError(f"Невідомий стан для очікувача: {target_state}")

        waiter.wait(
            InstanceIds=[self.instance_id],
            WaiterConfig={"Delay": 15, "MaxAttempts": max_attempts}
        )
        print(f"[SUCCESS] Інстанс {self.instance_id} успішно перейшов у стан '{target_state}'.")

    def get_instance_details(self) -> Dict[str, Any]:
        """Отримання повної інформації про мережеві та системні атрибути інстансу."""
        if not self.instance_id:
            raise ValueError("Ідентифікатор інстансу не визначено.")

        response = self.ec2_client.describe_instances(InstanceIds=[self.instance_id])
        instance_data = response["Reservations"][0]["Instances"][0]
        
        details = {
            "InstanceId": instance_data.get("InstanceId"),
            "InstanceType": instance_data.get("InstanceType"),
            "State": instance_data.get("State", {}).get("Name"),
            "PublicIpAddress": instance_data.get("PublicIpAddress", "N/A"),
            "PrivateIpAddress": instance_data.get("PrivateIpAddress", "N/A"),
            "AvailabilityZone": instance_data.get("Placement", {}).get("AvailabilityZone"),
            "LaunchTime": str(instance_data.get("LaunchTime")),
            "Architecture": instance_data.get("Architecture"),
            "VirtualizationType": instance_data.get("VirtualizationType"),
            "Tags": {tag["Key"]: tag["Value"] for tag in instance_data.get("Tags", [])}
        }
        return details

    def stop_instance(self):
        """Зупинка працюючого інстансу."""
        print(f"[INFO] Відправка сигналу зупинки інстансу {self.instance_id}...")
        self.ec2_client.stop_instances(InstanceIds=[self.instance_id])
        self.wait_for_state("stopped")

    def start_instance(self):
        """Повторний запуск зупиненого інстансу."""
        print(f"[INFO] Відправка сигналу старту інстансу {self.instance_id}...")
        self.ec2_client.start_instances(InstanceIds=[self.instance_id])
        self.wait_for_state("running")

    def terminate_instance(self):
        """Безповоротне знищення віртуальної машини."""
        print(f"[INFO] Ініціалізація процедури утилізації (Termination) {self.instance_id}...")
        self.ec2_client.terminate_instances(InstanceIds=[self.instance_id])
        self.wait_for_state("terminated")
        print(f"[SUCCESS] Ресурси інстансу {self.instance_id} повністю вивільнено.")
```

#### Крок 4. Головна програма оркестрації `main.py`

Створіть головний виконуваний скрипт, який об'єднує всі кроки в цілісний автоматизований сценарій:

```python
import os
import json
from tabulate import tabulate
from scripts.ec2_manager import EC2LifecycleManager


def main():
    print("=================================================================")
    print("  АВТОМАТИЗАЦІЯ ЖИТТЄВОГО ЦИКЛУ IaaS ІНСТАНСУ AWS EC2 (BOTO3)   ")
    print("=================================================================\n")

    config_file = os.path.join("config", "settings.json")
    user_data_file = os.path.join("scripts", "user_data.sh")
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    manifest_file = os.path.join(output_dir, "instance_manifest.json")

    # Ініціалізація менеджера
    manager = EC2LifecycleManager(config_path=config_file)

    try:
        # 1. Створення та запуск інстансу
        manager.provision_instance(user_data_script_path=user_data_file)

        # 2. Очікування стану RUNNING
        manager.wait_for_state("running")

        # 3. Збирання метаданих
        details = manager.get_instance_details()

        # Виведення результатів у форматі таблиці
        table_data = [[k, v] for k, v in details.items() if k != "Tags"]
        print("\n" + tabulate(table_data, headers=["Параметр", "Значення"], tablefmt="fancy_grid"))
        
        print("\nПризначені теги інстансу:")
        tags_table = [[k, v] for k, v in details["Tags"].items()]
        print(tabulate(tags_table, headers=["Ключ тегу", "Значення"], tablefmt="grid"))

        # Збереження маніфесту в JSON-файл
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(details, f, indent=4, ensure_ascii=False)
        print(f"\n[INFO] Повний маніфест інстансу збережено у: {manifest_file}")

        # 4. Демонстрація зупинки та повторного запуску
        print("\n--- Демонстрація переходу станів (Stop / Start) ---")
        manager.stop_instance()
        manager.start_instance()

        # 5. Очищення інфраструктури (Termination)
        print("\n--- Завершення лабораторної роботи та утилізація ресурсів ---")
        manager.terminate_instance()

    except Exception as ex:
        print(f"\n[ERROR] Виникла виключна ситуація: {str(ex)}")
        if manager.instance_id:
            print(f"[CLEANUP] Спроба екстреного знищення інстансу {manager.instance_id}...")
            try:
                manager.terminate_instance()
            except Exception as clean_err:
                print(f"[CLEANUP ERROR] Не вдалося видалити інстанс: {clean_err}")


if __name__ == "__main__":
    main()
```

---

### 3.3 Запуск, тестування та перевірка результатів

Для виконання розробленого комплексу перейдіть у кореневу директорію проєкту в терміналі та запустіть головний модуль:

```bash
python3 main.py
```

У разі коректного виконання вхідних даних у консолі буде відображено покроковий протокол проходження всіх фаз життєвого циклу, статус очікувачів та таблицю згенерованих мережевих метаданих інстансу:

```text
=================================================================
  АВТОМАТИЗАЦІЯ ЖИТТЄВОГО ЦИКЛУ IaaS ІНСТАНСУ AWS EC2 (BOTO3)   
=================================================================

[INFO] SSH-ключ 'cps-lab1-keypair' знайдено в інфраструктурі.
[INFO] Security Group 'cps-lab1-secgroup' знайдено (ID: sg-08e1a5f4c39b22a01).
[INFO] Запуск процедури створення інстансу типу 't3.micro'...
[SUCCESS] Запит прийнято. Створено інстанс з ідентифікатором: i-0a8b9c7d6e5f41234
[INFO] Очікування переходу інстансу i-0a8b9c7d6e5f41234 у стан 'running'...
[SUCCESS] Інстанс i-0a8b9c7d6e5f41234 успішно перейшов у стан 'running'.

╒════════════════════╤══════════════════════════════════════╕
│ Параметр           │ Значення                             │
╞════════════════════╪══════════════════════════════════════╡
│ InstanceId         │ i-0a8b9c7d6e5f41234                  │
│ InstanceType       │ t3.micro                             │
│ State              │ running                              │
│ PublicIpAddress    │ 3.120.145.89                         │
│ PrivateIpAddress   │ 172.31.24.112                        │
│ AvailabilityZone   │ eu-central-1a                        │
│ LaunchTime         │ 2026-08-29 18:30:15+00:00            │
│ Architecture       │ x86_64                               │
│ VirtualizationType │ hvm                                  │
╘════════════════════╧══════════════════════════════════════╛

Призначені теги інстансу:
+-------------+--------------------------+
| Ключ тегу   | Значення                 |
+-------------+--------------------------+
| Name        | cps-reference-controller |
| Project     | CyberPhysicalSystem      |
| Environment | Laboratory               |
| ManagedBy   | Boto3-Automation         |
| Owner       | Student-Master           |
+-------------+--------------------------+

[INFO] Повний маніфест інстансу збережено у: output/instance_manifest.json

--- Демонстрація переходу станів (Stop / Start) ---
[INFO] Відправка сигналу зупинки інстансу i-0a8b9c7d6e5f41234...
[INFO] Очікування переходу інстансу i-0a8b9c7d6e5f41234 у стан 'stopped'...
[SUCCESS] Інстанс i-0a8b9c7d6e5f41234 успішно перейшов у стан 'stopped'.
[INFO] Відправка сигналу старту інстансу i-0a8b9c7d6e5f41234...
[INFO] Очікування переходу інстансу i-0a8b9c7d6e5f41234 у стан 'running'...
[SUCCESS] Інстанс i-0a8b9c7d6e5f41234 успішно перейшов у стан 'running'.

--- Завершення лабораторної роботи та утилізація ресурсів ---
[INFO] Ініціалізація процедури утилізації (Termination) i-0a8b9c7d6e5f41234...
[INFO] Очікування переходу інстансу i-0a8b9c7d6e5f41234 у стан 'terminated'...
[SUCCESS] Інстанс i-0a8b9c7d6e5f41234 успішно перейшов у стан 'terminated'.
[SUCCESS] Ресурси інстансу i-0a8b9c7d6e5f41234 повністю вивільнено.
```

---

## 4. Вимоги до змісту звіту

Звіт з лабораторної роботи оформлюється у форматі PDF відповідно до стандартів вищої школи та повинен містити такі обов'язкові розділи:
1. **Титульна сторінка** із зазначенням найменування закладу вищої освіти, кафедри, назви дисципліни, теми лабораторної роботи, прізвища та ініціалів здобувача, академічної групи та номера індивідуального варіанта.
2. **Мета роботи, технічне завдання та вихідні параметри** індивідуального варіанта згідно з таблицею 3.1.
3. **Архітектурна схема** створеного обчислювального вузла з описом параметрів мережі, правил Security Group, характеристик vCPU/RAM та конфігурації тому EBS.
4. **Повний вихідний текст розроблених файлів** (`settings.json`, `user_data.sh`, `ec2_manager.py`, `main.py`) із детальними авторськими коментарями.
5. **Скріншоти виконання програми в терміналі**, що підтверджують успішне створення, зміну станів (`pending` $\to$ `running` $\to$ `stopped` $\to$ `terminated`) та вміст згенерованого файлу `instance_manifest.json`.
6. **Аналітичний висновок**, у якому наведено оцінку ефективності автоматизації засобами Boto3, аналіз накладних витрат на час очікування операцій та розрахунок орієнтовної вартості оренди інстансу за розрахунковою формулою.

---

## 5. Контрольні запитання для захисту роботи

1. У чому полягає фундаментальна відмінність між низькорівневим клієнтом (`boto3.client`) та високорівневим ресурсом (`boto3.resource`) у бібліотеці Boto3, і які переваги надає кожен підхід?
2. Опишіть повний автомат станів інстансу AWS EC2. Чому перехід зі стану `stopping` у стан `stopped` зупиняє нарахування плати за обчислювальні ресурси процесора, але зберігає витрати на дисковий том EBS?
3. Яким чином протокол автентифікації AWS Signature Version 4 (SigV4) гарантує цілісність, автентичність та захист від атак повторного відтворення (Replay Attacks) для кожного виклику API?
4. Розкрийте принцип функціонування механізму очікувачів (Waiters) у Boto3. За якою математичною моделлю розраховується сумарний час очікування, і які параметри конфігурації визначають поведінку очікувача?
5. Чим відрізняється поведінка правил фільтрації трафіку в Security Groups від мережевих списків контролю доступу (Network ACL) при забезпеченні мережевого доступу до віртуальної машини?
6. Поясніть призначення та механізм виконання скриптів `User Data` під час початкового розгортання інстансу. В який саме момент життєвого циклу ОС виконується цей скрипт?
7. За якою математичною формулою здійснюється розрахунок вартості оренди віртуальних машин EC2, і в яких випадках використання цінової моделі Spot Instances є економічно виправданим для кіберфізичних систем?
