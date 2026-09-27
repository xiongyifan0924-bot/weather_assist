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


def _query_geocoding(name, prefer_cn=False):
    """单次地理编码查询。prefer_cn 用于拼音兜底：拼音是猜出来的，
    强制优先取中国境内匹配，避免 'luan' 命中罗安达这类跨国错配。"""
    params = {"name": name, "count": 5 if prefer_cn else 1, "language": "zh", "format": "json"}
    try:
        response = requests.get(GEOCODING_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        results = response.json().get("results") or []
    except Exception as e:
        print(f"Geocoding API Error: {e}")
        return None

    if prefer_cn:
        for r in results:
            if r.get("country_code") == "CN":
                return _extract(r)
    return _extract(results[0]) if results else None


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

    Open-Meteo 的中文条目覆盖不全（连云港、厦门、温州等查不到），
    因此中文查不到时降级到拼音查询。不做前缀截断：截断可能命中同名
    小镇（如"连云港连岛"截成"连云"会返回福建的地点）并静默给出错误
    地区的数据，宁可报错让模型换标准地名重试。
    """
    result = _query_geocoding(city)
    if result:
        return result

    for fallback in (city_en, _to_pinyin(city)):
        if fallback and fallback != city:
            result = _query_geocoding(fallback, prefer_cn=True)
            if result:
                return result

    return None, None, None, None, None


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