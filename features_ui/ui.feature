Feature: API Automation

  Scenario Outline: Execute POST API tests
    When I want to execute <application> <end_points> <filename_pattern> API post tests

  Examples:
    | application | end_points | filename_pattern |
    | restful     | objects    | data_post.json   |

  Scenario Outline: Execute GET API tests
    When I want to execute <application> <end_points> <filename_pattern> API get tests

  Examples:
    | application | end_points | filename_pattern   |
    | restful     | objects    | response_POST.json |
