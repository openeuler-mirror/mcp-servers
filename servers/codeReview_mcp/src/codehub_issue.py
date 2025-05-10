import requests
import argparse
import json
url = {
    "obmm": "https://codehub-y.huawei.com/api/v4/projects/3160459/issues",
    "test": "https://codehub-y.huawei.com/api/v4/projects/4411866/issues"
}

headers = {
    "PRIVATE-TOKEN": "G_YfzsbZqrjH4ygfQ4sJ74Sn"
}
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--title', required=True, help='issue标题')
    parser.add_argument('--desc', required=True, help='issue描述')
    parser.add_argument('--project', default="test", help='目标项目')
    args = parser.parse_args()
    
    data = {
        "title": f"[LLM REVIEWER] {args.title}",
        "description": f"**这是一个LLM自动产生的issue：**\n{args.desc}",
        "labels": "FROM_LLM",
        "issue_category": "Other"
    }
    response = requests.post(url[args.project], headers=headers, data=data)
    jsontext = json.loads(response.text)
    print(jsontext['web_url'])

if __name__ == "__main__":
    main()
