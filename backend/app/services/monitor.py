monitoring_active = False


def start_monitoring():
    global monitoring_active
    monitoring_active = True
    return {"active": True}


def stop_monitoring():
    global monitoring_active
    monitoring_active = False
    return {"active": False}


def get_monitoring_status():
    return {"active": monitoring_active}
