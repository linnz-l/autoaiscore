from datetime import datetime, timedelta, timezone
import json
import requests
import os
import openai
import xml.etree.ElementTree as ET

# ================= 核心配置区域 =================
# 1. 你想追踪的营养学期刊或关键词（这里默认帮你配好了最顶级的几本营养学期刊）
SEARCH_TERM = '"Am J Clin Nutr"[Journal] OR "Nutr Rev"[Journal] OR "J Nutr"[Journal] OR "Prog Lipid Res"[Journal]'

# 2. 定制你的 AI 评审角色
SYSTEM_PROMPT = "You are a leading nutrition science expert and clinical dietitian. You are skilled at selecting robust, high-quality, and groundbreaking nutritional research, clinical trials, and dietary studies."
# ===============================================

access_token = os.getenv('GITHUB_TOKEN')
openaiapikey = os.getenv('OPENAI_API_KEY')

client = openai.OpenAI(
    api_key=openaiapikey,
    base_url="https://api.deepseek.com/v1"
)

def extract_scores(text):
    if not text or text == "No abstract available.":
        return "N/A", "N/A"
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Given the text '{text}', evaluate this article with two scores:\n"
                                            "1. Research Score (0-100):\n"
                                            "2. Social Impact Score (0-100):\n"
                                            "Provide the scores in the following format:\n"
                                            "Research Score: <score>\n"
                                            "Social Impact Score: <score>"}
            ],
            max_tokens=100,
            temperature=0.5
        )
        generated_text = response.choices[0].message.content.strip()  
        
        research_score_start = generated_text.find("Research Score:")
        research_score = generated_text[research_score_start+len("Research Score:"):].split("\n")[0].strip()

        social_impact_score_start = generated_text.find("Social Impact Score:")
        social_impact_score = generated_text[social_impact_score_start+len("Social Impact Score:"):].strip()
        return research_score, social_impact_score
    except Exception:
        return "N/A", "N/A"

def get_pubmed_articles_via_api(term, max_results=5):
    """彻底抛弃RSS，直接调用PubMed官方API获取最新文献"""
    articles = []
    try:
        # 步骤 1: 在 PubMed 中搜索过去 7 天的文章 ID
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        search_params = {
            "db": "pubmed",
            "term": term,
            "reldate": 7,       # 过去 7 天
            "datetype": "pdat",  # 基于出版日期
            "retmode": "json",
            "retmax": max_results
        }
        search_res = requests.get(search_url, params=search_params).json()
        id_list = search_res.get("esearchresult", {}).get("idlist", [])
        
        if not id_list:
            print("Past 7 days had no new articles. Trying to fetch latest 5 anyway for testing...")
            # 如果过去7天真的没文章，去掉时间限制，强行抓最近的5条用来做通道测试
            search_params.pop("reldate")
            search_params.pop("datetype")
            search_res = requests.get(search_url, params=search_params).json()
            id_list = search_res.get("esearchresult", {}).get("idlist", [])
            
        if not id_list:
            return articles

        # 步骤 2: 根据 ID 批量获取文章的具体标题和摘要明细 (XML 格式)
        fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(id_list),
            "retmode": "xml"
        }
        fetch_res = requests.get(fetch_url, params=fetch_params)
        root = ET.fromstring(fetch_res.content)

        # 步骤 3: 解析 XML 提取数据
        for article in root.findall(".//PubmedArticle"):
            # 提取标题
            title_node = article.find(".//ArticleTitle")
            title = "".join(title_node.itertext()).strip() if title_node is not None else "No Title Available"
            
            # 提取摘要
            abstract_nodes = article.findall(".//AbstractText")
            if abstract_nodes:
                abstract = " ".join(["".join(node.itertext()).strip() for node in abstract_nodes])
            else:
                abstract = "No abstract available."
                
            # 提取 DOI
            doi = "No DOI available"
            for el in article.findall(".//ArticleId"):
                if el.attrib.get("IdType") == "doi":
                    doi = el.text
                    break
                    
            articles.append({"title": title, "abstract": abstract, "doi": doi})
    except Exception as e:
        print(f"PubMed API Error: {e}")
    return articles

# 获取数据
pubmed_articles = get_pubmed_articles_via_api(SEARCH_TERM, max_results=5)
new_articles_data = []

for idx, abstract_data in enumerate(pubmed_articles):
    print(f"Processing article {idx+1}/{len(pubmed_articles)}...")
    title = abstract_data["title"]
    research_score, social_impact_score = extract_scores(abstract_data["abstract"])
    doi = abstract_data["doi"]

    new_articles_data.append({
        "title": title,
        "research_score": research_score,
        "social_impact_score": social_impact_score,
        "doi": doi
    })
    
issue_title = f"Weekly Article Matching (PubMed API) - {datetime.now().strftime('%Y-%m-%d')}"
issue_body = f"Below are the article matching results (Top 5) fetched via PubMed API:\n\n"

if not new_articles_data:
    issue_body += "⚠️ No articles found matching your criteria this week."
else:
    for article_data in new_articles_data:
        issue_body += f"- **Title**: {article_data['title']}\n"
        issue_body += f"  **Research Score**: {article_data['research_score']}\n"
        issue_body += f"  **Social Impact Score**: {article_data['social_impact_score']}\n"
        issue_body += f"  **DOI**: {article_data['doi']}\n\n"

def create_github_issue(title, body, access_token):
    repo = os.getenv('GITHUB_REPOSITORY')
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {access_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {"title": title, "body": body}
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.status_code == 201:
        print("Issue created successfully!")
    else:
        print("Failed to create issue:", response.text)

create_github_issue(issue_title, issue_body, access_token)
