import requests
import json
import functools

try:
    from pypinyin import lazy_pinyin
except ImportError:  # 云端构建缺依赖时降级到仅中文查询，避免整个应用起不来
    lazy_pinyin = None

TIMEOUT = 10
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _extract(result):
    return (result["latitude"], result["longitude"], result["name"],
            result.get("country", ""), result.get("admin1", ""))


# 行政区级别：省级中心 > 地级市 > 区县 > 普通村镇
_ADMIN_LEVEL = {"PPLC": 5, "PPLA": 4, "PPLA2": 3, "PPLA3": 2, "PPLA4": 1}


def _candidates(name):
    """单次地理编码查询的全部候选，只保留中国境内"""
    params = {"name": name, "count": 8, "language": "zh", "format": "json"}
    try:
        response = requests.get(GEOCODING_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        return [r for r in (response.json().get("results") or [])
                if r.get("country_code") == "CN"]
    except Exception as e:
        print(f"Geocoding API Error: {e}")
        return []


def _rank(result, names):
    """排序依据：名字是否对得上 > 人口 > 行政区级别。

    气象库不按重要性排序——「长沙」的第一条是重庆的同名村（人口 4.7 万），
    真正的湖南省会（人口 309 万）排在后面。而只看名字又会踩另一个坑：
    「大同」会选中黑龙江的同名镇（行政区级别更高但人口远小于山西大同市）。
    两个信号一起用才稳。
    """
    nm = (result.get("name") or "").lower()
    name_ok = 2 if nm in names else 0
    return (name_ok, result.get("population") or 0,
            _ADMIN_LEVEL.get(result.get("feature_code") or "", 0))


def _to_pinyin(city):
    if lazy_pinyin is None:
        return None
    try:
        return "".join(lazy_pinyin(city))
    except Exception:
        return None


@functools.lru_cache(maxsize=256)
def get_coordinates(city, city_en=None):
    """获取城市的经纬度信息。

    依次用「中文市名 / 中文名 / 拼音市名 / 拼音名」查询并合并候选，选最优。
    中文地名库覆盖不全（「连云港」中文查不到，必须用拼音）且同名异地极多，
    所以既要多形式查询，也要按名字+人口+级别综合排序。

    名字完全对不上时返回失败——实测「稻城」在库里只有谐音「道成」（江苏），
    「香格里拉」的中文名只匹配到河北的社区。这类情况宁可让上层报错，
    也不能拿错误地区的天气当目的地数据用。
    """
    py = _to_pinyin(city) or ""
    names = {city.lower(), city.lower() + "市"}
    if py:
        names |= {py, py + "shi"}
    if city_en:
        names.add(city_en.lower())

    forms = [city + "市", city]
    if py:
        forms += [py + "shi", py]
    if city_en:
        forms.append(city_en)

    best = None
    for form in dict.fromkeys(forms):
        for r in _candidates(form):
            if best is None or _rank(r, names) > _rank(best, names):
                best = r

    if best is None or _rank(best, names)[0] == 0:
        return None, None, None, None, None
    return _extract(best)


def get_weather_data(lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,precipitation,relative_humidity_2m",
        "wind_speed_unit": "ms",
        "forecast_days": 16,
        "timezone": "auto",
    }
    try:
        response = requests.get(FORECAST_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Forecast API Error: {e}")
        return None


def fetch_weather_for_city(city, city_en=None):
    """
    供大模型 Function Calling 直接调用的组合函数。
    将经纬度查询与天气查询合并，按天聚合后格式化为精简文本。
    """
    lat, lon, name, country, admin1 = get_coordinates(city, city_en)
    if lat is None or lon is None:
        return json.dumps(
            {"error": f"气象库中查不到 '{city}' 的位置。请改用标准的地级市或县级市名称"
                      f"重新调用本工具，不要使用景点、岛屿、街道等小地名。"},
            ensure_ascii=False,
        )

    weather_data = get_weather_data(lat, lon)
    if not weather_data:
        return json.dumps(
            {"error": "Open-Meteo 气象服务请求失败，与地名无关，请告知用户数据源暂时不可用。"},
            ensure_ascii=False,
        )

    hourly = weather_data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precips = hourly.get("precipitation", [])
    winds = hourly.get("wind_speed_10m", [])

    daily = {}
    for t, temp, p, w in zip(times, temps, precips, winds):
        # 预报末端会有不完整的时段（值为 None），跳过
        if temp is None or p is None or w is None:
            continue
        entry = daily.setdefault(t[:10], {"tmax": temp, "tmin": temp, "precip": 0.0, "wind": 0.0, "hours": 0})
        entry["tmax"] = max(entry["tmax"], temp)
        entry["tmin"] = min(entry["tmin"], temp)
        entry["precip"] += p
        entry["wind"] = max(entry["wind"], w)
        entry["hours"] += 1

    # 只输出数据完整的天，末日不足 20 小时的残缺数据会误导判断
    complete = {day: d for day, d in daily.items() if d["hours"] >= 20}

    # 带上省份供模型核对定位是否合理
    location = f"{name}（{admin1}，{country}）" if admin1 else f"{name}（{country}）"
    summary = f"已获取 {location} 未来 {len(complete)} 天气象数据，坐标 {lat:.3f}, {lon:.3f}：\n"
    summary += "日期 | 最高温 | 最低温 | 日累计降水 | 最大风速\n"
    for day, d in complete.items():
        summary += (f"{day} | {d['tmax']:.1f}°C | {d['tmin']:.1f}°C | "
                    f"{d['precip']:.1f}mm | {d['wind']:.1f}m/s\n")
    return summary