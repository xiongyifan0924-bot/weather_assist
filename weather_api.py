import requests
import json
import functools  # <--- 1. 引入内置库

@functools.lru_cache(maxsize=128)  # <--- 2. 加上这行魔法代码，开启缓存！
def get_coordinates(city):
    """获取城市的经纬度信息"""
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=zh&format=json"
    # ... 下面的代码完全不用动 ...
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if "results" in data and len(data["results"]) > 0:
            result = data["results"][0]
            return result["latitude"], result["longitude"], result["name"], result.get("country", "")
    except Exception as e:
        print(f"Geocoding API Error: {e}")
    return None, None, None, None

def get_weather_data(lat, lon):
    # 这里改成了 forecast_days=7
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,wind_speed_10m,precipitation,relative_humidity_2m&wind_speed_unit=ms&forecast_days=7&timezone=auto"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Forecast API Error: {e}")
        return None

def fetch_weather_for_city(city):
    """
    供大模型 Function Calling 直接调用的组合函数。
    将经纬度查询与天气查询合并，并格式化为精简文本。
    """
    lat, lon, name, country = get_coordinates(city)
    if lat is None or lon is None:
        return json.dumps({"error": f"无法找到城市 {city} 的位置信息，请提示用户更换常用地名。"})
    
    weather_data = get_weather_data(lat, lon)
    if not weather_data:
        return json.dumps({"error": f"获取 {name} 的天气数据失败，请建议用户稍后重试。"})
    
    # 【抽取逻辑修改】：取未来 7 天（168小时），每间隔 6 小时抽样一次
    hourly = weather_data.get("hourly", {})
    times = hourly.get("time", [])[:168:6] 
    temps = hourly.get("temperature_2m", [])[:168:6]
    precips = hourly.get("precipitation", [])[:168:6]
    
    summary = f"已获取 {name} ({country}) 未来气象数据:\n"
    for t, temp, p in zip(times, temps, precips):
        summary += f"时间: {t}, 温度: {temp}°C, 降水: {p}mm\n"
    
    return summary