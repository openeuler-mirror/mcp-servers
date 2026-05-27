# Timezone Manager MCP Server

## Function Description

It provides the MCP tool for managing system time zones, including:

- Obtaining the current time zone
- Setting a new time zone
- Listing available time zones

## Dependencies

- tzdata
- python3
- fastapi
- uvicorn

## APIs

### Obtaining the Current Time Zone

`POST /get_timezone`
Return to the current system time zone.

### Setting a New Time Zone

`POST /set_timezone`

Parameter:
`timezone`: name of the time zone to be set (for example, "**Asia/Shanghai**")

### Listing Available Time Zones

`POST /list_timezones`

Return the list of all available time zones.

## How to Use

1. Ensure that dependencies have been installed.
2. Run the server:

```bash
uvicorn server:app --reload
```
