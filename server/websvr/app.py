from flask import Flask, render_template, request
from utils import devicesinfo,device_close,device_open,device_set_temp,device_set_fan,device_set_mode,device_close_heating

app = Flask(__name__)


@app.route("/")
def index():
    ac_list = [parse_ac_data(dev) for dev in devicesinfo()]
    return render_template("index.html", ac_list=ac_list)

@app.route("/desc")
def desc():
    myid = request.args.get("id", "")  
    for dev in devicesinfo():
        if int(dev['dev_address'])==int(myid):
           return render_template("desc.html", ac=parse_ac_data(dev))

@app.route("/edit_power",methods=['GET', 'POST'])
def edit_power():
    if request.method == 'GET':
        myid = request.args.get("id", "")  
        for dev in devicesinfo():
            if int(dev['dev_address'])==int(myid):
               return render_template("edit_power.html", ac=parse_ac_data(dev))
    elif request.method == 'POST':
        myid = request.form.get("id", "")  
        new_status = request.form.get('new_status')
        if new_status=='close':
           device_close(myid)
           return render_template("waiting.html", url=f'/')
        elif new_status=='open':
           device_open(myid)
           return render_template("waiting.html", url=f'/desc?id={myid}')

@app.route("/edit_target_temp",methods=['GET', 'POST'])
def edit_target_temp():
    if request.method == 'GET':
        myid = request.args.get("id", "")  
        for dev in devicesinfo():
            if int(dev['dev_address'])==int(myid):
               return render_template("edit_target_temp.html", ac=parse_ac_data(dev))
    elif request.method == 'POST':
        myid = int(request.form.get("id", "")) 
        new_temp= int(float(request.form.get('new_temp'))*10)
        device_set_temp(myid,new_temp)
        return render_template("waiting.html", url=f'/desc?id={myid}')

@app.route("/edit_fan",methods=['GET', 'POST'])
def edit_fan():
    if request.method == 'GET':
        myid = request.args.get("id", "")  
        for dev in devicesinfo():
            if int(dev['dev_address'])==int(myid):
               return render_template("edit_fan.html", ac=parse_ac_data(dev))
    elif request.method == 'POST':
        myid = int(request.form.get("id", "")) 
        new_fan= request.form.get('new_fan')
        arr={"高":0, "中":1, "低":2, "自动":3}
        if new_fan in arr:
            new_fan = arr[new_fan]
        else:
            new_fan = 3
        device_set_fan(myid,new_fan)
        return render_template("waiting.html", url=f'/desc?id={myid}')

@app.route("/edit_mode",methods=['GET', 'POST'])
def edit_mode():
    if request.method == 'GET':
        myid = request.args.get("id", "")  
        for dev in devicesinfo():
            if int(dev['dev_address'])==int(myid):
               return render_template("edit_mode.html", ac=parse_ac_data(dev))
    elif request.method == 'POST':
        myid = int(request.form.get("id", "")) 
        new_mode= request.form.get('new_mode')
        arr={"冷风":1, "热风":2, "换气":3, "地暖":4, "地暖热风":5}
        if new_mode in arr:
            new_mode = arr[new_mode]
            device_set_mode(myid,new_mode)
        return render_template("waiting.html", url=f'/desc?id={myid}')

@app.route("/edit_heating",methods=['GET', 'POST'])
def close_heating():
    if request.method == 'GET':
        myid = request.args.get("id", "")  
        for dev in devicesinfo():
            if int(dev['dev_address'])==int(myid):
               return render_template("edit_heating.html", ac=parse_ac_data(dev))
    elif request.method == 'POST':
        myid = int(request.form.get("id", "")) 
        device_close_heating(myid)
        return render_template("waiting.html", url=f'/desc?id={myid}')




def parse_ac_data(device):
    reg = device["register_values"]
    myid = int(device["dev_address"]) - 1
    return {
        "dev_address":myid+1,
        # Room names indexed by device address - 1, adjust to your installation
        "id": ["房间1", "房间2", "房间3", "房间4", "房间5", "房间6", "房间7"][myid],
        "power": "开" if reg[1] == 1 else "关",
        "mode": ["冷风", "热风", "换气", "地暖", "地暖热风"][reg[2] - 1],
        "fan": ["高", "中", "低", "自动"][reg[4]],
        "current_temp": float(reg[15]) / 10,
        "target_temp": float(reg[3]) / 10,
        "heating": "开" if reg[22]!=0 else "关",
        "insert_time": device["insert_time"],
    }


if __name__ == "__main__":
    # local debugging only, the container runs gunicorn instead
    app.run(debug=True, host="0.0.0.0", port=5000)
