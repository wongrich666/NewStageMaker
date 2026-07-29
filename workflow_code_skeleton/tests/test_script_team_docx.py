from __future__ import annotations

from pathlib import Path

from docx import Document

from workflow_code_skeleton.app.utils.txt_to_docx import convert_script_team


def test_script_team_docx_uses_episode_scene_and_script_styles(tmp_path: Path) -> None:
    source = tmp_path / "script.txt"
    output = tmp_path / "script.docx"
    source.write_text(
        "\n".join(
            [
                "《测试剧》",
                "",
                "第1集：《门外的人》",
                "场景1：出租屋｜夜｜内",
                "人物：艾拉、谢敛",
                "艾拉攥紧账单，门外传来三声敲门。",
                "艾拉：（压低声音，眉心微蹙）谁？",
                "艾拉OS：他不该知道这里。",
                "",
                "场景2：楼道｜夜｜内",
                "人物：谢敛",
                "▲谢敛把钥匙插进锁孔。",
                "",
                "第2集：《钥匙》",
                "场景1：楼道｜夜｜内",
                "人物：艾拉、谢敛",
                "谢敛：开门。",
            ]
        ),
        encoding="utf-8",
    )

    convert_script_team(str(source), str(output), title="测试剧")

    document = Document(output)
    paragraphs = [paragraph for paragraph in document.paragraphs if paragraph.text.strip()]
    by_text = {paragraph.text: paragraph for paragraph in paragraphs}

    assert "《测试剧》" in by_text
    assert by_text["第 1 集"].style.name == "Heading 1"
    assert by_text["1-1 出租屋｜夜｜内"].style.name == "Heading 2"
    assert by_text["1-2 楼道｜夜｜内"].style.name == "Heading 2"
    assert by_text["人物：艾拉、谢敛"].runs[0].bold is True
    assert by_text["△ 艾拉攥紧账单，门外传来三声敲门。"].runs[0].bold is not True
    assert by_text["艾拉：（压低声音，眉心微蹙）谁？"].runs[0].bold is True
    assert by_text["艾拉OS：他不该知道这里。"].runs[0].bold is True
